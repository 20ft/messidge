import sphinx_rtd_theme

extensions = ['sphinx.ext.autodoc']
autodoc_member_order = 'bysource'

templates_path = ['_templates']
source_suffix = '.rst'
master_doc = 'index'

# General information about the project.
project = 'Messidge'
copyright = '2017, David Preece'
author = 'David Preece'
version = ''
release = ''

language = None
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
pygments_style = 'sphinx'
todo_include_todos = False

html_theme = "sphinx_rtd_theme"
html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]
html_theme_options = {
    'collapse_navigation': False,
    'display_version': False
}
html_static_path = ['_static']
