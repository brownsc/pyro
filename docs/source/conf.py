import sphinx_rtd_theme
import re
import os
import sys

# import pkg_resources

# -*- coding: utf-8 -*-
#
# Pyro documentation build configuration file, created by
# sphinx-quickstart on Thu Jun 15 17:16:14 2017.
#
# This file is execfile()d with the current directory set to its
# containing dir.
#
# Note that not all possible configuration values are present in this
# autogenerated file.
#
# All configuration values have a default; values that are commented out
# serve to show the default.

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
sys.path.insert(0, os.path.abspath('../..'))

# -- General configuration ------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.intersphinx',  #
    'sphinx.ext.todo',  #
    'sphinx.ext.mathjax',  #
    'sphinx.ext.ifconfig',  #
    'sphinx.ext.viewcode',  #
    'sphinx.ext.githubpages',  #
    'sphinx.ext.autodoc',
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# General information about the project.
project = u'Pyro'
copyright = u'2017-2018, Uber Technologies, Inc'
author = u'Uber AI Labs'

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
# get the latest git tag with  the latest commit
# eg pyro-0.1.2-g4c52460
# this only matters if you host manually
version = re.sub('^v', '', os.popen('git describe --tags').read().strip())

# release version
release = version

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = None

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This patterns also effect to html_static_path and html_extra_path
exclude_patterns = []

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# If true, `todo` and `todoList` produce output, else they produce nothing.
todo_include_todos = True

# do not prepend module name to functions
add_module_names = False

# -- Options for HTML output ----------------------------------------------

# logo
html_logo = '_static/img/pyro_logo_wide.png'

# logo
html_favicon = '_static/img/favicon/favicon.ico'

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "sphinx_rtd_theme"
html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.

html_theme_options = {
    'navigation_depth': 3,
    'logo_only': True,
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']
html_style = 'css/pyro.css'

# -- Options for HTMLHelp output ------------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = 'Pyrodoc'

# -- Options for LaTeX output ---------------------------------------------

latex_elements = {
    # The paper size ('letterpaper' or 'a4paper').
    #
    # 'papersize': 'letterpaper',

    # The font size ('10pt', '11pt' or '12pt').
    #
    # 'pointsize': '10pt',

    # Additional stuff for the LaTeX preamble.
    #
    # 'preamble': '',

    # Latex figure (float) alignment
    #
    # 'figure_align': 'htbp',
}

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (master_doc, 'Pyro.tex', u'Pyro Documentation', u'Uber AI Labs', 'manual'),
]

# -- Options for manual page output ---------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [(master_doc, 'pyro', u'Pyro Documentation', [author], 1)]

# -- Options for Texinfo output -------------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (master_doc, 'Pyro', u'Pyro Documentation', author, 'Pyro',
     'Deep Universal Probabilistic Programming.', 'Miscellaneous'),
]

# Example configuration for intersphinx: refer to the Python standard library.
intersphinx_mapping = {
    'python': ('https://docs.python.org/3/', None),
    'torch': ('http://pytorch.org/docs/master/', None),
}

# document class constructors (__init__ methods):
""" comment out this functionality for now;
def skip(app, what, name, obj, skip, options):
    if name == "__init__":
        return False
    return skip


def setup(app):
    app.connect("autodoc-skip-member", skip)
"""

PYTORCH_SCRIPT = """
#!/bin/bash\n
pip install --upgrade pip
curl https://raw.githubusercontent.com/uber/pyro/dev/README.md > README.md\n
PYTORCH_BUILD_COMMIT=$(grep 'git checkout .* a well-tested commit' README.md | cut -f3 -d' ')\n
echo $PYTORCH_BUILD_COMMIT\n
PYTHON_VERSION=$(python -c 'import sys; version=sys.version_info[:3]; print("{0}{1}".format(*version))')\n
WHL_VERSION=${PYTORCH_VERSION}%2B${PYTORCH_BUILD_COMMIT}\n
PYTORCH_LINUX_PREFIX='https://d2fefpcigoriu7.cloudfront.net/pytorch-build/linux-cpu'\n
WHL_LOOKUP=PYTORCH_LINUX_PY_${PYTHON_VERSION}_WHL\n
mkdir tmp
curl -o tmp/pt.whl ${PYTORCH_LINUX_PREFIX}/${!WHL_LOOKUP}.whl\n
echo 'curled'; ls tmp\n
pip install tmp/*\n
rm -rf tmp
"""

with open('install.sh', 'w') as f:
    f.write(PYTORCH_SCRIPT)

# @jpchen's hack to get rtd builder to install latest pytorch
if 'READTHEDOCS' in os.environ:
    os.system('bash install.sh')
    os.system('rm -f install.sh')
