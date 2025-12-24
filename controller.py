#!/usr/bin/env python3
"""
MINISDN Controller - COMPLETE VERSION WITH FIXED ELECTION
"""
import sys
import time
import threading
import requests
import os
import random
from flask import Flask, jsonify, request
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import set_ev_cls, MAIN_DISPATCHER, CONFIG_DISPATCHER
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4, icmp

#configuration
node_id = os.environ.get('NODE_ID', 'node1')
WEB_PORTS = {'node1': 5001, 'node2': 5002, 'node3': 5003}
PEERS = {'node1', 'node2', 'node3'} - {node_id}

#cluster node
class ClusterState:
    def __init__(self, node_id):
        
        self.node_id = node_id
        self.role = "follower"
        self.leader_id = None
        self.current_term = 0
        self.voted_for = None
        self.switches = {}
        self.last_heartbeat_time = time.time()
        
        #random election timeout (8-12 seconds)
        self.election_timeout = random.uniform(8.0, 12.0)
        
        #only one election timer thread
        threading.Thread(target=self._election_timer, daemon=True).start()
    
    def _election_timer(self):
        """Monitor for leader heartbeat timeouts - SINGLE THREAD"""
        while True:
            time.sleep(0.5)  #check every 0.5 seconds
            
            #if we're leader, don't run elections
            if self.role == "leader":
                continue
                
            time_since_heartbeat = time.time() - self.last_heartbeat_time
            
            #use the random timeout, reset when we receive heartbeat/vote
            if time_since_heartbeat > self.election_timeout:
                print(f"[{self.node_id}] ⏰ Election timeout ({self.election_timeout:.1f}s)")
                self._start_election()
    
    def _start_election(self):
        """Start a new election"""
        if self.role == "leader":
            return  #leaders don't start elections
            
        print(f"[{self.node_id}] 🗳️  Starting election for term {self.current_term + 1}")
        
        self.role = "candidate"
        self.current_term += 1
        self.voted_for = self.node_id  #voted for myself
        votes_received = 1  #vote for self
        
        #Request votes from ALL peers (including ourselves)
        all_nodes = ['node1', 'node2', 'node3']
        for peer in all_nodes:
            if peer == self.node_id:
                continue  # Skip ourselves
                
            try:
                response = requests.post(
                    f"http://localhost:{WEB_PORTS[peer]}/request_vote",
                    json={'term': self.current_term, 'candidate': self.node_id},
                    timeout=1
                )
                if response.json().get('vote_granted'):
                    votes_received += 1
                    print(f"[{self.node_id}] ✅ Got vote from {peer}")
            except Exception as e:
                print(f"[{self.node_id}] ❌ Failed to get vote from {peer}: {e}")
        
        #win election if majority (3 nodes -> need 2 votes)
        total_nodes = len(all_nodes)
        if votes_received > total_nodes / 2:
            self._become_leader()
        else:
            self.role = "follower"
            print(f"[{self.node_id}] ❌ Election lost, only got {votes_received}/{total_nodes} votes")
            #reset election timeout for next try
            self.election_timeout = random.uniform(8.0, 12.0)
    
    def _become_leader(self):
        """Become the leader"""
        self.role = "leader"
        self.leader_id = self.node_id
        print(f"\n{'='*50}")
        print(f"🏆 [{self.node_id}] LEADER ELECTED (Term {self.current_term})")
        print(f"{'='*50}\n")
        
        #notify all connected switches about new master
        for switch_id in self.switches.keys():
            self.switches[switch_id]['master'] = self.node_id
        
        #start sending heartbeats
        threading.Thread(target=self._send_heartbeats, daemon=True).start()
    
    def _send_heartbeats(self):
        """Leader sends heartbeats to followers"""
        while self.role == "leader":
            time.sleep(2)  #Send every 2 seconds
            for peer in PEERS:
                try:
                    requests.post(
                        f"http://localhost:{WEB_PORTS[peer]}/heartbeat",
                        json={'term': self.current_term, 'leader': self.node_id},
                        timeout=1
                    )
                except Exception as e:
                    print(f"[{self.node_id}] ❌ Failed to send heartbeat to {peer}: {e}")
    
    def receive_heartbeat(self, leader_id, term):
        """Receive heartbeat from leader"""
        if term >= self.current_term:
            #Update term and reset election timeout
            self.current_term = term
            self.leader_id = leader_id
            self.role = "follower"
            self.voted_for = None  #reset vote for next election
            self.last_heartbeat_time = time.time()
            self.election_timeout = random.uniform(8.0, 12.0)  #reset timeout
            
            if leader_id != self.node_id:
                print(f"[{self.node_id}] ❤️  Heartbeat from {leader_id} (term {term})")
                
                #update switch master information
                for switch_id in self.switches.keys():
                    self.switches[switch_id]['master'] = leader_id

state = ClusterState(node_id)

#Flask API
web_app = Flask(__name__)

@web_app.route('/status')
def get_status():
    """Get node status"""
    return jsonify({
        'node_id': state.node_id,
        'role': state.role,
        'leader': state.leader_id,
        'term': state.current_term,
        'voted_for': state.voted_for,
        'switches': list(state.switches.keys()),
        'switch_details': state.switches
    })

@web_app.route('/heartbeat', methods=['POST'])
def receive_heartbeat():
    """Receive heartbeat from leader"""
    data = request.get_json()
    state.receive_heartbeat(data['leader'], data['term'])
    return jsonify({'status': 'ack', 'node': node_id})

@web_app.route('/request_vote', methods=['POST'])
def request_vote():
    """Handle vote requests from candidates"""
    import time
    
    data = request.get_json()
    candidate_term = data['term']
    candidate_id = data['candidate']
    
    print(f"[{node_id}] 📨 Vote request from {candidate_id} (term {candidate_term}, our term {state.current_term})")
    
    #Reset election timeout when we vote for someone
    vote_granted = False
    
    #Grant vote if:
    #1. Candidate's term is higher than ours, OR
    #2. Same term and we haven't voted yet
    if candidate_term > state.current_term:
        state.current_term = candidate_term
        state.voted_for = candidate_id
        state.leader_id = None
        state.role = "follower"
        state.last_heartbeat_time = time.time()  #Reset heartbeat timer
        state.election_timeout = random.uniform(8.0, 12.0)  #Reset timeout
        vote_granted = True
        print(f"[{node_id}] ✅ Voted for {candidate_id} (term {candidate_term})")
    
    elif candidate_term == state.current_term and state.voted_for in [None, candidate_id]:
        state.voted_for = candidate_id
        state.last_heartbeat_time = time.time()  #Reset heartbeat timer
        state.election_timeout = random.uniform(8.0, 12.0)  #Reset timeout
        vote_granted = True
        print(f"[{node_id}] ✅ Voted for {candidate_id} (term {candidate_term})")
    else:
        print(f"[{node_id}] ❌ Rejected vote for {candidate_id}")
    
    return jsonify({'vote_granted': vote_granted, 'term': state.current_term})

@web_app.route('/force_election', methods=['POST'])
def force_election():
    """Force this node to start an election (for testing)"""
    if state.role != "leader":
        state._start_election()
        return jsonify({'status': 'election_started', 'term': state.current_term})
    return jsonify({'status': 'already_leader', 'term': state.current_term})

# --- Ryu Controller ---
class MinisdnController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        
        print(f"\n{'='*60}")
        print(f"🚀 [{node_id}] MINISDN Controller STARTED")
        print(f"   Ryu Port: {6633 + int(node_id[-1]) - 1}")
        print(f"   Web API: http://localhost:{WEB_PORTS[node_id]}")
        print(f"{'='*60}\n")
        
        # Start Flask web server
        web_port = WEB_PORTS[node_id]
        threading.Thread(target=lambda: web_app.run(
            host='0.0.0.0', port=web_port, debug=False, use_reloader=False
        ), daemon=True).start()
    
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Called when switch connects - INSTALLS REQUIRED FLOWS"""
        datapath = ev.msg.datapath
        switch_id = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        #Store datapath for later use
        self.datapaths[switch_id] = datapath
        
        print(f"\n[{node_id}] 🔌 Switch s{switch_id} CONNECTED")
        
        #Store switch info
        master = state.leader_id if state.leader_id else node_id
        state.switches[switch_id] = {
            'master': master,
            'ports': {},
            'connected_at': time.time()
        }
        
        #Initialize MAC learning table for this switch
        self.mac_to_port[switch_id] = {}
        
        #Install table-miss flow to send packets to controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=0,
            match=match,
            instructions=inst
        )
        datapath.send_msg(mod)
        
        print(f"   ✓ Installed table-miss flow on s{switch_id}")
        print(f"   ✓ Master: {master}")
        
        # Notify leader about new switch
        if state.role == "leader":
            print(f"   📢 Notifying cluster about new switch s{switch_id}")
    
    def add_flow(self, datapath, priority, match, actions):
        """Install a flow rule on switch"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst
        )
        datapath.send_msg(mod)
    
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """Handle incoming packets - MAC learning switch"""
        msg = ev.msg
        datapath = msg.datapath
        switch_id = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        
        #Parse packet
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        
        if not eth:
            return
        
        #Skip if not master for this switch
        if switch_id in state.switches and state.switches[switch_id]['master'] != node_id:
            # Forward to master if known
            master_id = state.switches[switch_id]['master']
            print(f"[{node_id}] 📤 Forwarding packet from s{switch_id} to master {master_id}")
            return
        
        #Learn MAC address
        if switch_id not in self.mac_to_port:
            self.mac_to_port[switch_id] = {}
        
        self.mac_to_port[switch_id][eth.src] = in_port
        
        print(f"[{node_id}] 📦 Packet on s{switch_id}: {eth.src[:8]} → {eth.dst[:8]} (port {in_port})")
        
        #If destination is known, send to that port, otherwise flood
        dst_port = self.mac_to_port[switch_id].get(eth.dst, ofproto.OFPP_FLOOD)
        
        actions = [parser.OFPActionOutput(dst_port)]
        
        #Install flow if not flooding and not broadcast
        if dst_port != ofproto.OFPP_FLOOD and not eth.dst.startswith('ff:ff:ff:ff:ff:ff'):
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst)
            self.add_flow(datapath, 1, match, actions)
            print(f"   ✓ Installed flow: {eth.src[:8]} → {eth.dst[:8]} via port {dst_port}")
        
        #Send packet out
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data
        )
        datapath.send_msg(out)
    
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER])
    def state_change_handler(self, ev):
        """Handle switch disconnection"""
        datapath = ev.datapath
        if ev.state == 0:  # Switch disconnected
            switch_id = datapath.id
            if switch_id in state.switches:
                print(f"\n[{node_id}] ❌ Switch s{switch_id} DISCONNECTED")
                del state.switches[switch_id]
                if switch_id in self.mac_to_port:
                    del self.mac_to_port[switch_id]
                if switch_id in self.datapaths:
                    del self.datapaths[switch_id]

#Helper function to check if we should handle this switch
def is_master_for_switch(switch_id):
    """Check if this node is master for the given switch"""
    if switch_id in state.switches:
        return state.switches[switch_id]['master'] == node_id
    return True  # Assume master if switch not registered
