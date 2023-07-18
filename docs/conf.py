# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import arke

project = arke.__name__
copyright = arke.__copyright__
author = arke.__author__
version = arke.__version__

# -- General configuration --
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    # built-in exts
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- AutoDoc Config --

autoclass_content = "class"
autodoc_typehints = "signature"
autodoc_typehints_format = "short"
autodoc_preserve_defaults = True

autodoc_default_options = {
    "show-inheritance": True,
    "exclude-members": "__init__",
}

autodoc_type_aliases = {
    "HTTP_METHODS": "HTTP_METHODS"
}

# -- Intersphinx Config --

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- Napoleon Config --

napoleon_google_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = False

# -- Options for HTML output --
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]
