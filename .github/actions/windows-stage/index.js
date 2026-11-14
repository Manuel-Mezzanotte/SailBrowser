// One stage of the Windows build, adapted from helium-windows. The repository
// is copied to C:\sail (see windows-prepare); the Chromium tree lives in
// C:\sail\build\src and travels between stages as the artifact zip.
const core = require('@actions/core');
const io = require('@actions/io');
const exec = require('@actions/exec');
const {DefaultArtifactClient} = require('@actions/artifact');
const glob = require('@actions/glob');

const path = require('path');
const os = require('os');

const REPO = 'C:\\sail';
const BUILD = path.join(REPO, 'build');

async function uploadWithRetries(artifact, name, files, root, options) {
    const attempts = 5;
    for (let attempt = 1; attempt <= attempts; ++attempt) {
        try {
            await artifact.deleteArtifact(name);
        } catch (e) {
            // Nothing to replace.
        }
        try {
            await artifact.uploadArtifact(name, files, root, options);
            return;
        } catch (e) {
            console.error(`Upload artifact failed: ${e}`);
            if (attempt === attempts) throw e;
            await new Promise(r => setTimeout(r, 10000));
        }
    }
}

async function run() {
    const started_at = Number(process.env.HELIUM_JOB_STARTED_AT) || Math.floor(Date.now() / 1000);

    process.on('SIGINT', function() {
    })
    const from_artifact = core.getBooleanInput('from_artifact', {required: true});
    const upload_final = core.getBooleanInput('upload_final', {required: false});
    const arm = core.getBooleanInput('arm', {required: false})
    console.log(`artifact: ${from_artifact}, upload_final: ${upload_final}`);

    const artifact = new DefaultArtifactClient();
    const artifactName = arm ? 'build-artifact-arm64' : 'build-artifact-x86_64';

    if (upload_final) {
        const finalDirectory = core.getInput('final_directory', {required: true});
        const globber = await glob.create(path.join(finalDirectory, 'Sail*'),
            {matchDirectories: false});
        const packageList = await globber.glob();
        if (packageList.length === 0) throw `no Sail packages in ${finalDirectory}`;
        await uploadWithRetries(artifact, arm ? 'sail-windows-arm64' : 'sail-windows-x64',
            packageList, finalDirectory, {retentionDays: 30, compressionLevel: 0});

        const {exitCode, stdout} = await exec.getExecOutput('python', [
            'helium-chromium\\utils\\helium_version.py',
            '--print',
            '--tree', 'helium-chromium',
            '--platform-tree', 'windows'
        ], {cwd: REPO});
        if (exitCode !== 0) throw `failed getting version: ${exitCode}`;
        core.setOutput('version', stdout.trim());
        core.setOutput('finished', true);
        return;
    }

    if (from_artifact) {
        const artifactInfo = await artifact.getArtifact(artifactName);
        await artifact.downloadArtifact(artifactInfo.artifact.id, {path: BUILD});
        await exec.exec('7z', ['x', path.join(BUILD, 'artifacts.zip'), `-o${BUILD}`, '-y']);
        await io.rmRF(path.join(BUILD, 'artifacts.zip'));
    }

    const args = ['windows\\build.py', '--ci', String(started_at)]
    if (process.env.HELIUM_BUILD_JOBS) {
        args.push('-j', process.env.HELIUM_BUILD_JOBS);
    } else if (process.env.RUNNER_ENVIRONMENT === 'github-hosted') {
        const jobs = Math.max(1, Math.min(os.availableParallelism(),
            Math.floor(os.freemem() / (3 * 1024 ** 3))));
        args.push('-j', String(jobs));
    }
    if (arm)
        args.push('--arm')

    const retCode = await exec.exec('python', args, {cwd: REPO, ignoreReturnCode: true});
    // 42: the stage ran out of time and the next one continues.
    if (retCode > 0 && retCode !== 42) {
        throw `Unexpected return code: ${retCode}`
    }
    core.setOutput('finished', retCode === 0);

    const package_here = retCode === 0 && core.getBooleanInput('package_here') &&
        Date.now() / 1000 - started_at < 5 * 60 * 60;
    core.setOutput('package_here', package_here);

    if (!package_here && core.getBooleanInput('save_artifact')) {
        await exec.exec('7z', ['a', '-tzip', path.join(REPO, 'artifacts.zip'),
            path.join(BUILD, 'src'), '-mx=3', '-mtc=on'], {ignoreReturnCode: true});
        await uploadWithRetries(artifact, artifactName, [path.join(REPO, 'artifacts.zip')],
            REPO, {retentionDays: 4, compressionLevel: 0});
    }
}

run().catch(err => core.setFailed(err.message || String(err)));
