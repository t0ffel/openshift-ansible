# The role deploys Elasticsearch cluster on top of OpenShift

## Topology

The deployment supports 4 kinds of node roles:
* master
* client
* data
* data-client

We explicitly don't support combining masters with any other node type.
`es_node_topology` variable holds the description of the cluster node
topology.

### Masters

`es_node_topology.masters` describes how many masters will run. Single
DeploymentConfig will be created for all masters.
`replicas` field define how many masters to spin up (replicas in Kubernetes
notation).
`limits` define Kubernetes pod limits
`nodeSelector` define Kuberenetes pod selector

### Clients

`es_node_topology.clients` describes how many client nodes will run.
`limits` define Kubernetes pod limits
`nodeSelector` define Kuberenetes pod selector

### Data nodes

`es_node_topology.data` is an array that describes how each data client is structured. Each entry in the array corresponds to individual DeploymentConfig.
`limits` define Kubernetes pod limits
`nodeSelector` define Kuberenetes pod selector

### Data-Client nodes

TODO
