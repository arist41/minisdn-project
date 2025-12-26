# Distributed SDN Controller Cluster

Implementation of communication between SDN controllers for network state awareness via a 3-node cluster with Raft-based leader election.

# TECH STACK
- Clustering: Raft-inspired consensus (heartbeats, random timeout, elections)
- Controllers: Ryu (chosen for simplicity and lack of native clustering)
- Communication: Flask HTTP API between nodes
- Containerization: Docker for isolation

# STATUS
- Control Plane (Consensus & Failover): WORKING
- Data Plane (Ryu switch control): NOT WORKING

# KNOWN ISSUE & NEXT STEP
The Ryu event handlers do not execute due to a threading conflict with Flask in the same process. The fix is to separate Ryu and Flask into two independent processes communicating via a local socket or queue.

# SETUP & DEMO

1. Build and start the cluster:
   docker build -t my-ryu .
   docker compose up -d
   docker compose logs -f

2. Monitor cluster status (separate terminal):
   python3 test_cluster.py

3. Simulate leader failure (separate terminal):
   //Stop the current leader (node1, node2, or node3)
   docker compose stop node1
   //To restart it later:
   docker compose start node1

Cleanup: docker compose down
