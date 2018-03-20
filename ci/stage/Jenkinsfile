#!/usr/bin/env groovy
/**
  This is the Jenkinsfile for the Elasticsearch deployment in stage OpenShift project
**/
properties(
  [
    [$class: 'BuildConfigProjectProperty', name: '', namespace: '', resourceVersion: '', uid: ''],
    buildDiscarder(logRotator(artifactDaysToKeepStr: '', artifactNumToKeepStr: '10', daysToKeepStr: '', numToKeepStr: '10')),
    [$class: 'HudsonNotificationProperty', enabled: false],
    [$class: 'RebuildSettings', autoRebuild: false, rebuildDisabled: false],
    parameters(
      [
        string(defaultValue: '0312_es5_dev', description: 'commit ref hash, branch, or tag to build', name: 'ELASTICSEARCH_BRANCH'),
        string(defaultValue: 'dh-stage-storage', description: 'OpenShift Project to deploy Elasticsearch into', name: 'ELASTICSEARCH_PROJECT'),
      ]
    ),
    pipelineTriggers([])
  ]
)

ansiColor('xterm') {
  timestamps {
    node('dhslave') {
      configFileProvider([configFile( fileId: 'kubeconfig', variable: 'KUBECONFIG')]){
        wrap([$class: 'MaskPasswordsBuildWrapper', varMaskRegexes: [[regex: '\\(item=\\{\'key\'.*\'value\'.*$']]]) {
            stage('Checkout SCMs') {
              checkout_scms()
            }
            stage('Trigger Deployment Playbook') {
              run_deployment()
            }
          
        }
      }
    }
  }
}

def checkout_scms() {
    checkout poll: false, scm: [
      $class: 'GitSCM',
      branches: [[name: "*/0312_es5_dev"]],
      doGenerateSubmoduleConfigurations: false,
      extensions: [
        [$class: 'WipeWorkspace'],
        [$class: 'RelativeTargetDirectory', relativeTargetDir: 'openshift-ansible']
      ],
      submoduleCfg: [],
      userRemoteConfigs: [[url: 'https://github.com/t0ffel/openshift-ansible']]
    ]
    checkout poll: false, scm: [
      $class: 'GitSCM',
      branches: [[name: "*/master"]],
      doGenerateSubmoduleConfigurations: false,
      extensions: [
        [$class: 'WipeWorkspace'],
        [$class: 'RelativeTargetDirectory', relativeTargetDir: 'dh-ci-util']
      ],
      submoduleCfg: [],
      userRemoteConfigs: [[url: 'https://gitlab.cee.redhat.com/asherkho/dh-ci-util.git']]
    ]
}

def run_deployment() {
  try {
      sh '''
# Preconfiguration

# Change to working project
# FIXME: this shouldn't be required because the ansible script targets a provided project,
# but for some reason Jenkins (or something else) overrides this unless the project is manually changed
oc project $ELASTICSEARCH_PROJECT
oc projects
cp $WORKSPACE/dh-ci-util/inventory/hosts $WORKSPACE/openshift-ansible

# Run Ansible Script
cd $WORKSPACE/openshift-ansible
ansible-playbook -i hosts \
--extra-vars="
kubeconfig=$KUBECONFIG
openshift_logging_elasticsearch_namespace=$ELASTICSEARCH_PROJECT
generated_certs_dir=$WORKSPACE/dh-ci-util/certificates/stage-es-certs/
"  playbooks/upshift-stage-es-no-cert-regen.yaml

'''
  } catch (err) {
    echo 'Exception caught, being re-thrown...'
    throw err
  }
}
