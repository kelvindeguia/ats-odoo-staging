# -*- coding: utf-8 -*-
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

import json

from odoo.addons.http_routing.models.ir_http import slug, unslug
from odoo.addons.website.controllers.main import QueryURL
from odoo.addons.website_hr_recruitment.controllers.main  \
    import WebsiteHrRecruitment
from odoo import http, fields, SUPERUSER_ID
from odoo.http import request


class RecruitmentInherit(WebsiteHrRecruitment):
    """Override class WebsiteHrRecruitment"""
    def sitemap_jobs(env, rule, qs):
        if not qs or qs.lower() in '/jobs':
            yield {'loc': '/jobs'}
            
    @http.route(['/jobs',
        '/jobs/country/<model("res.country"):country>',
        '/jobs/department/<model("hr.department"):department>',
        '/jobs/country/<model("res.country"):country>/department/<model("hr.department"):department>',
        '/jobs/office/<int:office_id>',
        '/jobs/country/<model("res.country"):country>/office/<int:office_id>',
        '/jobs/department/<model("hr.department"):department>/office/<int:office_id>',
        '/jobs/country/<model("res.country"):country>/department/<model("hr.department"):department>/office/<int:office_id>',        
        '/jobs/search_content',
    ], type='http', auth="public", website=True, sitemap=sitemap_jobs)
    def jobs(self, country=None, department=None, office_id=None, **kwargs):
        env = request.env(context=dict(request.env.context, show_address=True, no_tag_br=True))

        Country = env['res.country']
        Jobs = env['hr.job']

        # List jobs available to current UID
        domain = request.website.website_domain()
        search_string = ''
        if kwargs.get('search'):
            search_string = kwargs.get('search', None)
        domain += [('name', 'ilike', search_string)]
        job_ids = Jobs.search(domain, order="is_published desc, sequence, no_of_recruitment desc").ids
        # Browse jobs as superuser, because address is restricted
        jobs = Jobs.sudo().browse(job_ids)

        # Default search by user country
        if not (country or department or office_id or kwargs.get('all_countries')):
            # country_code = request.session['geoip'].get('country_code')
            country_code = request.geoip.get('country_code')
            if country_code:
                countries_ = Country.search([('code', '=', country_code)])
                country = countries_[0] if countries_ else None
                if not any(j for j in jobs if j.address_id and j.address_id.country_id == country):
                    country = False

        # Filter job / office for country
        if country and not kwargs.get('all_countries'):
            jobs = [j for j in jobs if j.address_id is None or j.address_id.country_id and j.address_id.country_id.id == country.id]
            offices = set(j.address_id for j in jobs if j.address_id is None or j.address_id.country_id and j.address_id.country_id.id == country.id)
        else:
            offices = set(j.address_id for j in jobs if j.address_id)

        # Deduce departments and countries offices of those jobs
        departments = set(j.department_id for j in jobs if j.department_id)
        countries = set(o.country_id for o in offices if o.country_id)

        if department:
            jobs = [j for j in jobs if j.department_id and j.department_id.id == department.id]
        if office_id and office_id in [x.id for x in offices]:
            jobs = [j for j in jobs if j.address_id and j.address_id.id == office_id]
        else:
            office_id = False

        # Render page
        return request.render("website_hr_recruitment.index", {
            'jobs': jobs,
            'countries': countries,
            'departments': departments,
            'offices': offices,
            'country_id': country,
            'department_id': department,
            'office_id': office_id,
        })

    
    @http.route('/job/search', csrf=False, type="http", methods=['POST', 'GET'], auth="public", website=True)
    def search_contents(self, **kw):
        """get search result for auto suggestions"""
        strings = '%' + kw.get('name') + '%'
        try:
            domain = [('website_published', '=', True)]
            job = request.env['hr.job'].with_user(SUPERUSER_ID).search(domain)
            sql = """select id as res_id, name as name, name as value from hr_job where name ILIKE '{}'"""
            extra_query = ' and is_published = TRUE'
            limit = " limit 15"
            qry = sql + extra_query + limit
            request.cr.execute(qry.format(strings, tuple(job and job.ids)))
            name = request.cr.dictfetchall()
        except:
            name = {'name': 'None', 'value': 'None'}
        return json.dumps(name)
