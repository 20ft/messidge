import sphinx_rtd_theme

extensions = ['sphinx.ext.autodoc']
autodoc_member_order = 'bysource'

def skip(app, what, name, obj, skip, options):
    if name == "__init__":
        return False
    return skip

def setup(app):
    app.connect("autodoc-skip-member", skip)

templates_path = ['_templates']
source_suffix = '.rst'
master_doc = 'index'

# General information about the project.
project = 'Messidge'
copyright = '2017, David Preece'
author = 'David Preece'
version = '1.0.1'
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

