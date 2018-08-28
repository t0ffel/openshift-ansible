#!/usr/bin/env python
'''oc_csr_approve module'''
# Copyright 2018 Red Hat, Inc. and/or its affiliates
# and other contributors as indicated by the @author tags.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json

from ansible.module_utils.basic import AnsibleModule

try:
    from json.decoder import JSONDecodeError
except ImportError:
    JSONDecodeError = ValueError

DOCUMENTATION = '''
---
module: oc_csr_approve

short_description: Retrieve, approve, and verify node client csrs

version_added: "2.4"

description:
    - Runs various commands to list csrs, approve csrs, and verify nodes are
      ready.

author:
    - "Michael Gugino <mgugino@redhat.com>"
'''

EXAMPLES = '''
# Pass in a message
- name: Place credentials in file
  oc_csr_approve:
    oc_bin: "/usr/bin/oc"
    oc_conf: "/etc/origin/master/admin.kubeconfig"
    node_list: ['node1.example.com', 'node2.example.com']
'''

CERT_MODE = {'client': 'client auth', 'server': 'server auth'}


def run_command(module, command, rc_opts=None):
    '''Run a command using AnsibleModule.run_command, or fail'''
    if rc_opts is None:
        rc_opts = {}
    rtnc, stdout, err = module.run_command(command, **rc_opts)
    if rtnc:
        result = {'failed': True,
                  'changed': False,
                  'msg': str(err),
                  'state': 'unknown'}
        module.fail_json(**result)
    return stdout


def get_ready_nodes(module, oc_bin, oc_conf):
    '''Get list of nodes currently ready vi oc'''
    # json output is necessary for consistency here.
    command = "{} {} get nodes -ojson".format(oc_bin, oc_conf)
    stdout = run_command(module, command)

    try:
        data = json.loads(stdout)
    except JSONDecodeError as err:
        result = {'failed': True,
                  'changed': False,
                  'msg': str(err),
                  'state': 'unknown'}
        module.fail_json(**result)

    ready_nodes = []
    for node in data['items']:
        if node.get('status') and node['status'].get('conditions'):
            for condition in node['status']['conditions']:
                # "True" is a string here, not a boolean.
                if condition['type'] == "Ready" and condition['status'] == 'True':
                    ready_nodes.append(node['metadata']['name'])
    return ready_nodes


def get_csrs(module, oc_bin, oc_conf):
    '''Retrieve csrs from cluster using oc get csr -ojson'''
    command = "{} {} get csr -ojson".format(oc_bin, oc_conf)
    stdout = run_command(module, command)
    try:
        data = json.loads(stdout)
    except JSONDecodeError as err:
        result = {'failed': True,
                  'changed': False,
                  'msg': str(err),
                  'state': 'unknown'}
        module.fail_json(**result)
    return data['items']


def parse_subject_cn(subject_str):
    '''parse output of openssl req -noout -subject to retrieve CN.
       example input:
         'subject=/C=US/CN=test.io/L=Raleigh/O=Red Hat/ST=North Carolina/OU=OpenShift\n'
         or
         'subject=C = US, CN = test.io, L = City, O = Company, ST = State, OU = Dept\n'
       example output: 'test.io'
    '''
    stripped_string = subject_str[len('subject='):].strip()
    kv_strings = [x.strip() for x in stripped_string.split(',')]
    if len(kv_strings) == 1:
        kv_strings = [x.strip() for x in stripped_string.split('/')][1:]
    for item in kv_strings:
        item_parts = [x.strip() for x in item.split('=')]
        if item_parts[0] == 'CN':
            return item_parts[1]


def process_csrs(module, csrs, node_list, mode):
    '''Return a dictionary of pending csrs where the format of the dict is
       k=csr name, v=Subject Common Name'''
    csr_dict = {}
    for item in csrs:
        status = item['status'].get('conditions')
        if status:
            # If status is not an empty dictionary, cert is not pending.
            continue
        if CERT_MODE[mode] not in item['spec']['usages']:
            continue
        name = item['metadata']['name']
        request_data = base64.b64decode(item['spec']['request'])
        command = "openssl req -noout -subject"
        # ansible's module.run_command accepts data to pipe via stdin as
        # as 'data' kwarg.
        rc_opts = {'data': request_data, 'binary_data': True}
        stdout = run_command(module, command, rc_opts=rc_opts)
        # parse common_name from subject string.
        common_name = parse_subject_cn(stdout)
        if common_name and common_name.startswith('system:node:'):
            # common name is typically prepended with system:node:.
            common_name = common_name.split('system:node:')[1]
        # we only want to approve csrs from nodes we know about.
        if common_name in node_list:
            csr_dict[name] = common_name

    return csr_dict


def confirm_needed_requests_present(module, not_ready_nodes, csr_dict):
    '''Ensure all non-Ready nodes have a csr, or fail'''
    nodes_needed = set(not_ready_nodes)
    for _, val in csr_dict.items():
        nodes_needed.discard(val)

    # check that we found all of our needed nodes
    if nodes_needed:
        missing_nodes = ', '.join(nodes_needed)
        result = {'failed': True,
                  'changed': False,
                  'msg': "Cound not find csr for nodes: {}".format(missing_nodes),
                  'state': 'unknown'}
        module.fail_json(**result)


def approve_csrs(module, oc_bin, oc_conf, csr_pending_list, mode):
    '''Loop through csr_pending_list and call:
       oc adm certificate approve <item>'''
    res_mode = "{}_approve_results".format(mode)
    base_command = "{} {} adm certificate approve {}"
    approve_results = []
    for csr in csr_pending_list:
        command = base_command.format(oc_bin, oc_conf, csr)
        rtnc, stdout, err = module.run_command(command)
        approve_results.append(stdout)
        if rtnc:
            result = {'failed': True,
                      'changed': False,
                      'msg': str(err),
                      res_mode: approve_results,
                      'state': 'unknown'}
            module.fail_json(**result)
    return approve_results


def get_ready_nodes_server(module, oc_bin, oc_conf, nodes_list):
    '''Determine which nodes have working server certificates'''
    ready_nodes_server = []
    base_command = "{} {} get --raw /api/v1/nodes/{}/proxy/healthz"
    for node in nodes_list:
        # need this to look like /api/v1/nodes/<node>/proxy/healthz
        command = base_command.format(oc_bin, oc_conf, node)
        rtnc, _, _ = module.run_command(command)
        if not rtnc:
            # if we can hit that api endpoint, the node has a valid server
            # cert.
            ready_nodes_server.append(node)
    return ready_nodes_server


def verify_server_csrs(module, result, oc_bin, oc_conf, node_list):
    '''We approved some server csrs, now we need to validate they are working.
       This function will attempt to retry 10 times in case of failure.'''
    # Attempt to try node endpoints a few times.
    attempts = 0
    # Find not_ready_nodes for server-side again
    nodes_server_ready = get_ready_nodes_server(module, oc_bin, oc_conf,
                                                node_list)
    # Create list of nodes that still aren't ready.
    not_ready_nodes_server = set([item for item in node_list if item not in nodes_server_ready])
    while not_ready_nodes_server:
        nodes_server_ready = get_ready_nodes_server(module, oc_bin, oc_conf,
                                                    not_ready_nodes_server)
        # if we have same number of nodes_server_ready now, all of the previous
        # not_ready_nodes are now ready.
        if len(nodes_server_ready) == len(not_ready_nodes_server):
            break
        attempts += 1
        if attempts > 9:
            result['failed'] = True
            result['rc'] = 1
            missing_nodes = not_ready_nodes_server - set(nodes_server_ready)
            msg = "Some nodes still not ready after approving server certs: {}"
            msg = msg.format(", ".join(missing_nodes))
            result['msg'] = msg


def run_module():
    '''Run this module'''
    module_args = dict(
        oc_bin=dict(type='path', required=False, default='oc'),
        oc_conf=dict(type='path', required=False, default='/etc/origin/master/admin.kubeconfig'),
        node_list=dict(type='list', required=True),
    )
    module = AnsibleModule(
        supports_check_mode=False,
        argument_spec=module_args
    )
    oc_bin = module.params['oc_bin']
    oc_conf = '--config={}'.format(module.params['oc_conf'])
    node_list = module.params['node_list']

    result = {'changed': False, 'rc': 0}

    nodes_ready = get_ready_nodes(module, oc_bin, oc_conf)
    # don't need to check nodes that are already ready.
    not_ready_nodes = [item for item in node_list if item not in nodes_ready]

    # Get all csrs, no good way to filter on pending.
    csrs = get_csrs(module, oc_bin, oc_conf)

    # process data in csrs and build a dictionary of client requests
    csr_dict = process_csrs(module, csrs, node_list, "client")

    # This method is fail-happy and expects all non-Ready nodes have available
    # csrs.  Handle failure for this method via ansible retry/until.
    confirm_needed_requests_present(module, not_ready_nodes, csr_dict)

    # save client_approve_results so we can report later.
    client_approve_results = approve_csrs(module, oc_bin, oc_conf, csr_dict,
                                          'client')
    result['client_approve_results'] = client_approve_results

    # # Server Cert Section # #
    # Find not_ready_nodes for server-side
    nodes_server_ready = get_ready_nodes_server(module, oc_bin, oc_conf,
                                                node_list)
    # Create list of nodes that definitely need a server cert approved.
    not_ready_nodes_server = [item for item in node_list if item not in nodes_server_ready]

    # Get all csrs again, no good way to filter on pending.
    csrs = get_csrs(module, oc_bin, oc_conf)

    # process data in csrs and build a dictionary of server requests
    csr_dict = process_csrs(module, csrs, node_list, "server")

    # This will fail if all server csrs are not present, but probably shouldn't
    # at this point since we spent some time hitting the api to see if the
    # nodes are already responding.
    confirm_needed_requests_present(module, not_ready_nodes_server, csr_dict)
    server_approve_results = approve_csrs(module, oc_bin, oc_conf, csr_dict,
                                          'server')
    result['server_approve_results'] = server_approve_results

    result['changed'] = bool(client_approve_results) or bool(server_approve_results)

    verify_server_csrs(module, result, oc_bin, oc_conf, node_list)

    module.exit_json(**result)


def main():
    '''main'''
    run_module()


if __name__ == '__main__':
    main()
