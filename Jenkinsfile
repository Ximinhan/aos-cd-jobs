#!/usr/bin/env groovy

node {

    checkout scm
    def build = load("build.groovy")
    def buildlib = build.buildlib
    def commonlib = build.commonlib
    def slacklib = commonlib.slacklib
    commonlib.describeJob("build-sync", """
        <h2>Mirror latest 4.y images to nightlies</h2>
        <b>Timing</b>: usually automated. Human might use to revert or hand-advance nightly membership.

        This job gets the latest images from our candidate tags, syncs them to quay.io,
        and updates the imagestreams on api.ci which feed into nightlies on our
        release-controllers.

        build-sync runs a comprehensive set of checks validating the internal consistency
        of the proposed imagestream, and may halt the process accordingly. It can be considered
        the main artbiter.

        For more details see the <a href="https://github.com/openshift/aos-cd-jobs/blob/master/jobs/build/build-sync/README.md" target="_blank">README</a>
    """)

    // Please update README.md if modifying parameter names or semantics
    stage("sync") {
        sh "sleep 30"
        echo "sleep 30"
    }
}
