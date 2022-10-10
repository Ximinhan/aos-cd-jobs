from github import Github
from errata_tool import Erratum
import yaml
import re
import os
import koji
import click
from pyartcd import constants, exectools, util
from pyartcd.cli import cli, click_coroutine, pass_runtime
from pyartcd.runtime import Runtime


class OperatorSDKPipeline:
    def __init__(self, runtime: Runtime, group: str, assembly: str, updatelatest: bool) -> None:
        self.runtime = runtime
        self.group = group
        self.version = group.split("-")[1]
        self.assembly = assembly
        self.updatelatest = updatelatest

        self._jira_client = runtime.new_jira_client()
        self._github_client = runtime.new_github_client()
        self.session = koji.ClientSession("https://brewhub.engineering.redhat.com/brewhub")
        self.ocp_build_data_repo = self._github_client.get_repo("openshift/ocp-build-data")
        self.release_file = self.ocp_build_data_repo.get_contents("release.yaml",ref=group)
        self.release_yaml = yaml.load(self.release_file.decoded_content,Loader=yaml.FullLoader)
        self.extra_ad_id = self.release_yaml.releases[assembly]['assembly']['group']['advisories']['extras']
        self.parent_jira_key = self.release_yaml.releases[assembly]['assembly']['group']['release_jira']
        self.imagePath = 'registry-proxy.engineering.redhat.com/rh-osbs/openshift-ose-operator-sdk'


    async def run(self):
        # check if build exist
        et_builds = Erratum(errata_id = self.extra_ad_id).errata_builds
        sdk_build = [ i for i in et_builds[f'OSE-{self.version}-RHEL-8'] if re.search("openshift-enterprise-operator-sdk-container*", i)]
        if sdk_build == []:
            # build dosen't exist, update jira then close
            self._update_jira(self.parent_jira_key, "no new build in this release")
            return
        # get build digest list
        build = self.session.getBuild(sdk_build[0])
        archlist = ["amd64", "arm64", "ppc64le", "s390x"]
        for arch in archlist:
            await self._extract_binaries(arch, build)
        self._update_jira(self.parent_jira_key, "operator_sdk_sync job : {}".format(os.environ.get("BUILD_URL")))


    async def _extract_binaries(self, arch, build):
        shasum = await exectools.cmd_assert_async(f"oc image info --filter-by-os {arch} -o json {build} | jq .digest")
        sdkVersion = await exectools.cmd_assert_async(
            f"oc image info --filter-by-os {arch} -o json {build} | jq .config.container_config.Labels.version")
        
        if arch == 'amd64':
            rarch = 'x86_64'
        elif arch == 'arm64':
            rarch = 'aarch64'
        else:
            rarch = arch
        tarballFilename = f"operator-sdk-${sdkVersion}-linux-${rarch}.tar.gz"
        cmd = f"rm -rf ./${rarch} && mkdir ./${rarch}"
        cmd = cmd + " && " + f"oc image extract ${self.imagePath}@${shasum} --path /usr/local/bin/operator-sdk:./${rarch}/ --confirm"
        cmd = cmd + " && " + "chmod +x operator-sdk"
        cmd = cmd + " && " + f"tar --create --preserve-order --gzip --verbose --file ${tarballFilename} ./${rarch}/operator-sdk"
        cmd = cmd + " && " + f"ln -s ${tarballFilename} operator-sdk-linux-${rarch}.tar.gz && rm -f ./${rarch}/operator-sdk"
        await exectools.cmd_assert_async(cmd)
        if arch == 'amd64':
            tarballFilename = f"operator-sdk-${sdkVersion}-darwin-${rarch}.tar.gz"
            cmd = f"oc image extract ${self.imagePath}@${shasum} --path /usr/share/operator-sdk/mac/operator-sdk:./${rarch}/ --confirm"
            cmd = cmd + " && " + "chmod +x operator-sdk"
            cmd = cmd + " && " + f"tar --create --preserve-order --gzip --verbose --file ${tarballFilename} ./${rarch}/operator-sdk"
            cmd = cmd + " && " + f"ln -s ${tarballFilename} operator-sdk-darwin-${rarch}.tar.gz && rm -f ./${rarch}/operator-sdk"
            await exectools.cmd_assert_async(cmd)
        await self._sync_mirror(rarch)


    async def _sync_mirror(self, arch):
        extra_args = "--exclude '*' --include '*.tar.gz'"
        local_dir = f"./${arch}/"
        s3_path = f"/pub/openshift-v4/${arch}/clients/operator-sdk/${self.assembly}/"
        s3_path_latest = f"/pub/openshift-v4/${arch}/clients/operator-sdk/latest/"
        await exectools.cmd_assert_async(f"aws s3 sync --no-progress --exact-timestamps ${extra_args} --delete ${local_dir} s3://art-srv-enterprise${s3_path}")
        if self.updatelatest:
            await exectools.cmd_assert_async(f"aws s3 sync --no-progress --exact-timestamps ${extra_args} --delete ${local_dir} s3://art-srv-enterprise${s3_path_latest}")
    

    def _update_jira(self, parent_jira_id, comment):
        parent_jira = self._jira_client.get_issue(parent_jira_id)
        subtask = self._jira_client.get_issue(parent_jira.fields.subtasks[7].key)
        self._jira_client.add_comment(subtask, comment)
        self._jira_client.assign_to_me(subtask)
        self._jira_client.close_task(subtask)


@cli.command("operator-sdk-sync")
@click.option("-g", "--group", metavar='NAME', required=True,
              help="The group of components on which to operate. e.g. openshift-4.9")
@click.option("--assembly", metavar="ASSEMBLY_NAME", required=True,
              help="The name of an assembly. e.g. 4.9.1")
@click.option("--updatelatest", metavar="UPDATE_LATEST_SYMLINK", required=True, is_flag=True,
              help="Update latest symlink on mirror")
@pass_runtime
@click_coroutine
async def tarball_sources(runtime: Runtime, group: str, assembly: str, updatelatest: bool):
    pipeline = OperatorSDKPipeline(runtime, group, assembly, updatelatest)
    await pipeline.run()