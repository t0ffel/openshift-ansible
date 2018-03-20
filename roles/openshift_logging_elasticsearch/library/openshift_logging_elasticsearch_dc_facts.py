'''
---
module: openshift_logging_elasticsearch_dc_facts
version_added: ""
short_description: Gather facts about the OpenShift logging stack
description:
  - Determine the current facts about the OpenShift logging stack (e.g. cluster size)
options:
author: Red Hat, Inc
'''


# pylint: disable=redefined-builtin, unused-wildcard-import, wildcard-import
from subprocess import *   # noqa: F402,F403

# ignore pylint errors related to the module_utils import
# pylint: disable=redefined-builtin, unused-wildcard-import, wildcard-import
from ansible.module_utils.basic import *   # noqa: F402,F403

import yaml

EXAMPLES = """
- action: opneshift_logging_facts
"""

RETURN = """
"""

DEFAULT_OC_OPTIONS = ["-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}"]

# constants used for various labels and selectors
COMPONENT_KEY = "component"
LOGGING_INFRA_KEY = "logging-infra"
CLUSTER_NAME_LABEL = "cluster-name"
ES_ROLE_LABEL = "es-node-role"
# selectors for filtering resources
LOGGING_SELECTOR = LOGGING_INFRA_KEY + "=" + "support"
ROUTE_SELECTOR = "component=support, logging-infra=support, provider=openshift"
COMPONENTS = ["elasticsearch"]
SA_PREFIX = "system:serviceaccount:"


class OCBaseCommand(object):
    ''' The base class used to query openshift '''

    def __init__(self, binary, kubeconfig, namespace, username):
        ''' the init method of OCBaseCommand class '''
        self.binary = binary
        self.kubeconfig = kubeconfig
        self.username = username
        self.user = self.get_system_admin(self.kubeconfig)
        self.namespace = namespace

    # pylint: disable=no-self-use
    def get_system_admin(self, kubeconfig):
        ''' Retrieves the system admin '''
        with open(kubeconfig, 'r') as kubeconfig_file:
            config = yaml.load(kubeconfig_file)
            for user in config["users"]:
                if user["name"].startswith(self.username):
                    return user["name"]
        raise Exception("Unable to find system:admin in: " + kubeconfig)

    # pylint: disable=too-many-arguments, dangerous-default-value
    def oc_command(self, sub, kind, namespace=None, name=None, add_options=None):
        ''' Wrapper method for the "oc" command '''
        cmd = [self.binary, sub, kind]
        if name is not None:
            cmd = cmd + [name]
        if namespace is not None:
            cmd = cmd + ["-n", namespace]
        if add_options is None:
            add_options = []
#        import pdb; pdb.set_trace()
        cmd = cmd + ["--user=" + self.user, "--config=" + self.kubeconfig] + DEFAULT_OC_OPTIONS + add_options
        try:
            process = Popen(cmd, stdout=PIPE, stderr=PIPE)   # noqa: F405
            out, err = process.communicate(cmd)
            if len(err) > 0:
                if 'not found' in err:
                    return []
                if 'No resources found' in err:
                    return []
                raise Exception(err)
        except Exception as excp:
            err = "There was an exception trying to run the command '" + " ".join(cmd) + "' " + str(excp)
            raise Exception(err)

        return out


class OpenshiftESDCFacts(OCBaseCommand):
    ''' The class structure for holding the OpenshiftLogging Facts'''
    name = "facts"

    def __init__(self, logger, binary, kubeconfig, namespace, cluster_name, oc_username):
        # pylint: disable=too-many-arguments
        ''' The init method for OpenshiftESDCFacts '''
        super(OpenshiftESDCFacts, self).__init__(binary, kubeconfig, namespace, oc_username)
        self.logger = logger
        self.cluster_name = cluster_name
        self.facts = dict()
        self.selector = CLUSTER_NAME_LABEL + "=" + self.cluster_name

    def add_list_facts_for(self, kind, facts=None):
        ''' Add facts for the provided kind '''
        self.facts[kind] = facts

    def append_facts_for(self, comp, kind, facts=None):
        ''' Append facts for the provided kind to the list'''
        if comp not in self.facts:
            self.facts[comp] = list()
        if facts:
            facts['node_role'] = kind
            self.facts[comp].append(facts)

    def facts_for_dcs(self, selector):
        ''' Gathers facts for DCs based on selector in logging namespace '''
        dcs = self.oc_command("get", "deploymentconfig", namespace=self.namespace,
                              add_options=["-l", selector])
        return dcs.splitlines()

    def facts_for_masternodes(self):
        ''' Gathers facts for deploymentconfigs of masters in logging namespace '''
        selector = self.selector + ",es-node-role=master"
        dc_list = self.facts_for_dcs(selector)
        self.add_list_facts_for("masters", dc_list)

    def facts_for_nonmasternodes(self):
        ''' Gathers facts for deploymentconfigs of non-master nodes in logging namespace '''
        selector = self.selector + ",es-node-role!=master"
        dc_list = self.facts_for_dcs(selector)
        self.add_list_facts_for("nonmasters", dc_list)

    def detect_es_cluster_selector(self, namespace):
        '''Detect if old-style cluster is deployed that uses component=logging-es[-ops] label'''
        # Attempt to query by cluster name
        selector = CLUSTER_NAME_LABEL + "=" + self.cluster_name
        dclist = self.oc_command("get", "deploymentconfigs",
                                 namespace=namespace,
                                 add_options=["-l", selector])
        if len(dclist) != 0:
            self.selector = selector
            return selector
        else:
            old_selector = "component=" + self.cluster_name
            olddclist = self.oc_command("get", "deploymentconfigs",
                                        namespace=namespace,
                                        add_options=["-l", old_selector])
            if len(olddclist) != 0:
                self.selector = old_selector
                return old_selector
            else:
                raise Exception("No known cluster is deployed")

    # pylint: disable=no-self-use, too-many-return-statements
    def comp(self, name):
        ''' Does a comparison to evaluate the logging component '''
        if name.startswith(self.cluster_name):
            return "elasticsearch"
        else:
            return None

    def build_facts(self):
        ''' Builds the logging facts and returns them '''
        self.detect_es_cluster_selector(self.namespace)

        self.facts_for_masternodes()
        self.facts_for_nonmasternodes()

        return self.facts


def main():
    ''' The main method '''
    module = AnsibleModule(   # noqa: F405
        argument_spec=dict(
            admin_kubeconfig={"default": "/etc/origin/master/admin.kubeconfig", "type": "str"},
            oc_bin={"required": True, "type": "str"},
            openshift_namespace={"required": True, "type": "str"},
            elasticsearch_clustername={"required": True, "type": "str"},
            oc_username={"default": "system:admin", "type": "str"}
        ),
        supports_check_mode=False
    )
    try:
        cmd = OpenshiftESDCFacts(module, module.params['oc_bin'],
                                 module.params['admin_kubeconfig'],
                                 module.params['openshift_namespace'],
                                 module.params['elasticsearch_clustername'],
                                 module.params['oc_username'])
        module.exit_json(
            ansible_facts={"openshift_logging_elasticsearch_dc_facts": cmd.build_facts()}
        )
    # ignore broad-except error to avoid stack trace to ansible user
    # pylint: disable=broad-except
    except Exception as error:
        module.fail_json(msg=str(error))


if __name__ == '__main__':
    main()
