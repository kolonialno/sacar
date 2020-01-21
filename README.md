# Sacar

<p align="center">
  <a href="https://github.com/kolonialno/sacar/actions?query=workflow%3ATests">
    <img alt="GitHub Actions status" src="https://github.com/kolonialno/sacar/workflows/Tests/badge.svg?branch=master&event=push">
  </a>
</p>

Sacar is a service for automating deployment of Python services on Nomad based
on webhooks from GitHub. It was developed to improve the deployment process of
legacy applications at Kolonial.no without having to make major changes to the
code base.

**NOTE:** _This project is experimental and in early development._

---

## Application structure

Sacar runs as two jobs in your Nomad cluser; a single master and one slave on
each of the machines you are deploying too. The master service is the external
entrypoint to the service, and orchestrates all deployments. The slave nodes are
reponsible for more or less one thing; preparing a release for deployment on
each of the machines.

Sacar registers for webhooks and when anything is pushed to the master branch
all slaves will be asked to prepare the commit for deployment. Once all slaves
have finished preparing the version, it is considered ready for deployment. A
GitHub status check is created with an action that can be triggered to start a
deployment of the version.

It is also possible to automatically deploy new commits.

---

## Deployment artifacts

Sacar can deploy Python applications that are packaged as tarballs containing
both the dependencies and application code, together with scripts to control the
application lifetime. The tarball should have the following layout:

```
/my_app.tgz
├── wheels/             # Project dependencies as wheels
│   └── *.whl
├── requirements.txt    # Requirements file for installing everything in wheels/
├── bin/
│   ├── prepare         # Script to run after dependencies have been installed
│   └── deploy          # Script to run when the project should be deployed
├── my_app/             # Project files
│   └── *
└-- *                   # Other files are ignored
```

---

## Deployment flow

The deployment starts when code is pushed to GitHub. The master process receives
a webhook from GitHub and in returns creates a status check. In parallel a
GitHub action or similar should start building the tarball as described above
(see the examples directory for an example script). When the tarball has
finished building it should be dropped in a Google Cloud Storage bucket. Finally
the job building the tarball should notify Sacar that the tarball is ready.

When Sacar is notified that the tarball is ready it updates the GitHub status
check to inidicate that it has started preparing a commit for deployment. It
then notifies all slaves that they should download the tarball and prepare it.

The steps performed by the slaves as a part of the deployment process are:

1. Download the tarball
2. Extract the tarball
3. Create a lockfile
4. Create a virtual env for the project
5. Install dependencies from wheels into the project
6. Call the `bin/prepare` script to allow custom project setup

When all slaves have finished preparing a version, they update their state in
Consul. This state is watched by the master process. When the master sees that
all slaves have finished preparing the commit the GitHub check is updated to
indicate that the version is ready for deployment.

