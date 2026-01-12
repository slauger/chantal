API Reference
=============

This section contains the API documentation for Chantal's Python modules.

.. note::
   API documentation is generated from Python docstrings using Sphinx autodoc.

Core Modules
------------

Configuration
~~~~~~~~~~~~~

.. automodule:: chantal.core.config
   :members:
   :undoc-members:
   :show-inheritance:

Storage
~~~~~~~

.. automodule:: chantal.core.storage
   :members:
   :undoc-members:
   :show-inheritance:

Database Models
---------------

.. automodule:: chantal.db.models
   :members:
   :undoc-members:
   :show-inheritance:

Plugins
-------

Base Plugins
~~~~~~~~~~~~

.. automodule:: chantal.plugins.base
   :members:
   :undoc-members:
   :show-inheritance:

RPM Plugin
~~~~~~~~~~

.. note::
   RPM plugin documentation is available in the :doc:`../plugins/rpm-plugin` section.

   The RPM plugin is implemented in:

   - ``chantal.plugins.rpm.sync`` - RPM repository syncing
   - ``chantal.plugins.rpm.publisher`` - RPM metadata generation
   - ``chantal.plugins.rpm.models`` - RPM metadata models
   - ``chantal.plugins.rpm.parsers`` - Repomd.xml parsing

APT Plugin
~~~~~~~~~~

.. note::
   APT plugin documentation is available in the :doc:`../plugins/apt-plugin` section.

   The APT plugin is implemented in:

   - ``chantal.plugins.apt.sync`` - APT repository syncing
   - ``chantal.plugins.apt.publisher`` - Debian metadata generation
   - ``chantal.plugins.apt.models`` - Debian package models
   - ``chantal.plugins.apt.parsers`` - Release/Packages parsing

Helm Plugin
~~~~~~~~~~~

.. note::
   Helm plugin documentation is available in the :doc:`../plugins/helm-plugin` section.

   The Helm plugin is implemented in:

   - ``chantal.plugins.helm.sync`` - Helm chart syncing
   - ``chantal.plugins.helm.publisher`` - index.yaml generation
   - ``chantal.plugins.helm.models`` - Helm chart models

Alpine APK Plugin
~~~~~~~~~~~~~~~~~

.. note::
   Alpine APK plugin documentation is available in the :doc:`../plugins/apk-plugin` section.

   The APK plugin is implemented in:

   - ``chantal.plugins.apk.sync`` - APK package syncing
   - ``chantal.plugins.apk.publisher`` - APKINDEX generation
   - ``chantal.plugins.apk.models`` - APK package models

CLI Commands
------------

.. note::
   CLI command documentation is available in the :doc:`../user-guide/cli-commands` section.

   The CLI is implemented as modular command groups in:

   - ``chantal.cli.main`` - Entry point and command registration
   - ``chantal.cli.repo_commands`` - Repository management
   - ``chantal.cli.snapshot_commands`` - Snapshot management
   - ``chantal.cli.publish_commands`` - Publishing
   - ``chantal.cli.view_commands`` - View management
   - ``chantal.cli.content_commands`` - Content search
   - ``chantal.cli.db_commands`` - Database management
   - ``chantal.cli.pool_commands`` - Storage pool management
