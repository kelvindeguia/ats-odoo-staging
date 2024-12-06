# -*- coding: utf-8 -*-
#
##########################     CLOUDROITS   ######################################
#
#    Copyright (C) Cloudroits <https://www.cloudroits.com>.
#    This program is free software: you can modify
#    it under the terms of the GNU Affero General Public License (AGPL) as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
###################################################################################

{
    'name': 'Website Job Search',
    'version': '15.0',
    "category": "Website",
    'author': 'Cloudroits',
    'website': "https://www.cloudroits.com",
    'maintainer': 'Cloudroits',
    'company': 'Cloudroits',
    'summary': """Search functionality in website jobs page""",
    'description': """Add searchbox in the website jobs page to filter jobs based on the given search term. 
                    Autocompletes job suggestions based on search text""",
    'depends': ['website_hr_recruitment'],
    'license': 'AGPL-3',
    'data': ['views/job_view.xml',
             ],
     'assets': {
        'web.assets_frontend': [
            'odoo_website_job_search/static/src/js/search.js'
        ]
    },
    'images': ['static/description/images/odoo_website_job_search_banner.png'],
    'installable': True,
    'auto_install': False,
    'application': False,
}
