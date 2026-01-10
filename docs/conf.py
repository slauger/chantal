# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
sys.path.insert(0, os.path.abspath('../src'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Chantal'
copyright = '2026, Simon Lauger'
author = 'Simon Lauger'

version = '1.0'
release = '1.0'

# Project description
html_short_title = 'Chantal Documentation'
html_title = 'Chantal - Unified Repository Mirroring Tool'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',  # Google/NumPy docstring support
    'sphinx.ext.todo',
    'myst_parser',  # Markdown support
]

# MyST parser configuration
myst_enable_extensions = [
    'colon_fence',
    'deflist',
    'html_image',
    'linkify',
    'replacements',
    'smartquotes',
    'tasklist',
]

# Support both .rst and .md files
source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# Show todos
todo_include_todos = True



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

# Read the Docs theme options
html_theme_options = {
    'navigation_depth': 4,
    'collapse_navigation': False,
    'sticky_navigation': True,
    'includehidden': True,
    'titles_only': False,
}

# Add GitHub link
html_context = {
    'display_github': True,
    'github_user': 'slauger',
    'github_repo': 'chantal',
    'github_version': 'main',
    'conf_py_path': '/docs/',
}

# Favicon and logo
# html_logo = '_static/logo.png'
# html_favicon = '_static/favicon.ico'

# -- Options for intersphinx extension ---------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html#configuration

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
}
