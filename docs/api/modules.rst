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

.. automodule:: chantal.plugins.rpm
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: chantal.plugins.rpm_sync
   :members:
   :undoc-members:
   :show-inheritance:

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
