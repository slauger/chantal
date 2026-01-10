Chantal Documentation
=====================

**Chantal** - A unified CLI tool for offline repository mirroring.

*Because every other name was already taken.*

.. image:: https://img.shields.io/badge/version-1.0-blue
   :alt: Version 1.0

.. image:: https://img.shields.io/badge/python-3.10+-blue
   :alt: Python 3.10+

Overview
--------

Chantal is a Python-based CLI tool for offline repository mirroring, inspired by pulp-admin, reposync, aptly, and bandersnatch.

**The Problem:** Enterprise environments need offline mirrors of package repositories with:

- Version control (snapshots for rollback)
- Efficient storage (deduplication across repos)
- Support for multiple ecosystems (RPM, DEB/APT, PyPI)
- RHEL subscription support
- Simple management

**The Solution:** One tool. One workflow. Content-addressed storage. Immutable snapshots.

**Repository Type Support:**

+---------------------+----------------------------------+-------------------+
| Type                | Description                      | Status            |
+=====================+==================================+===================+
| RPM/DNF/YUM         | RHEL, CentOS, Fedora, Rocky, ... | ✅ **Available**  |
+---------------------+----------------------------------+-------------------+
| DEB/APT             | Debian, Ubuntu                   | 🚧 Planned        |
+---------------------+----------------------------------+-------------------+
| PyPI                | Python Package Index             | 🚧 Planned        |
+---------------------+----------------------------------+-------------------+
| Alpine APK          | Alpine Linux                     | 🚧 Planned        |
+---------------------+----------------------------------+-------------------+
| Helm Charts         | Kubernetes Helm repositories     | 🚧 Planned        |
+---------------------+----------------------------------+-------------------+
| npm/yarn            | Node.js package registries       | 🔬 Research       |
+---------------------+----------------------------------+-------------------+
| RubyGems            | Ruby package registry            | 🔬 Research       |
+---------------------+----------------------------------+-------------------+
| NuGet               | .NET package registry            | 🔬 Research       |
+---------------------+----------------------------------+-------------------+
| Go Modules          | Go package repositories          | 🔬 Research       |
+---------------------+----------------------------------+-------------------+
| Terraform Provider  | Terraform provider registry      | 🔬 Research       |
+---------------------+----------------------------------+-------------------+

**Legend:** ✅ Available | 🚧 Planned | 🔬 Research Phase

See `GitHub Issues <https://github.com/slauger/chantal/issues>`_ for details and progress.

Features
--------

- 🔄 **Unified Mirroring** - Support for multiple package ecosystems in one tool

  - ✅ **RPM/DNF/YUM** (RHEL, CentOS, Fedora, Rocky, Alma) - *Available now*
  - 🚧 **DEB/APT, PyPI, Alpine APK, Helm Charts** - *Planned*
  - 🔬 **npm, RubyGems, NuGet, Go Modules, Terraform** - *Research phase*

- 📦 **Deduplication** - Content-addressed storage (SHA256), packages stored once
- 📸 **Snapshots** - Immutable point-in-time repository states for patch management
- 🔍 **Views** - Virtual repositories combining multiple repos (e.g., BaseOS + AppStream + EPEL)
- 🔌 **Modular** - Plugin architecture for repository types
- 🚫 **No Daemons** - Simple CLI tool (optional scheduler for future automation)
- 📁 **Static Output** - Serve with any webserver (Apache, NGINX)
- 🔐 **RHEL CDN Support** - Client certificate authentication for Red Hat repos
- 🎯 **Smart Filtering** - Pattern-based package filtering with post-processing
- ⚡ **Fast Updates** - Check for updates without downloading (like ``dnf check-update``)

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   user-guide/installation
   user-guide/quickstart
   user-guide/cli-commands
   user-guide/views
   user-guide/workflows

.. toctree::
   :maxdepth: 2
   :caption: Configuration

   configuration/overview
   configuration/repositories
   configuration/filters
   configuration/ssl-authentication

.. toctree::
   :maxdepth: 2
   :caption: Architecture

   architecture/overview
   architecture/content-addressed-storage
   architecture/database-schema
   architecture/plugin-system

.. toctree::
   :maxdepth: 2
   :caption: Plugins

   plugins/overview
   plugins/rpm-plugin
   plugins/custom-plugins

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/modules

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
