# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import datetime

import pytz

from odoo import api, fields, models, _
from odoo.addons.web_editor.controllers.main import handle_history_divergence


class Job(models.Model):
    _name = "hr.job"
    _description = "Job Position"
    _inherit = ['mail.thread']
    _order = 'sequence'

    active = fields.Boolean(default=True)
    name = fields.Char(string='Job Position', required=True, index='trigram', translate=True)
    sequence = fields.Integer(default=10)
    expected_employees = fields.Integer(compute='_compute_employees', string='Total Forecasted Employees', store=True,
                                        help='Expected number of employees for this job position after new recruitment.')
    no_of_employee = fields.Integer(compute='_compute_employees', string="Current Number of Employees", store=True,
                                    help='Number of employees currently occupying this job position.')
    no_of_recruitment = fields.Integer(string='Headcount Demand', copy=False,
                                       help='Number of new employees you expect to recruit.')
    no_of_hired_employee = fields.Integer(string='Hired Employees', copy=False,
                                          help='Number of hired employees for this job position during recruitment phase.')
    employee_ids = fields.One2many('hr.employee', 'job_id', string='Employees', groups='base.group_user')
    description = fields.Html(string='Job Description')
    requirements = fields.Text('Requirements')
    department_id = fields.Many2one('hr.department', string='Client Name',
                                    domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    contract_type_id = fields.Many2one('hr.contract.type', string='Employment Type')

    # Custom Fields
    x_requisition_id = fields.Many2one('hr.requisition', string='Requisition ID')
    x_category = fields.Selection(
        [('client services', 'Client Services'), ('sales team', 'Sales Team'), ('support hiring', 'Support Hiring')],
        string="Category", related='department_id.x_category')
    x_department_id_str = fields.Char('Admin Only - Department ID')
    x_requestor = fields.Selection(
        [('effy bongco', 'Effy Bongco'), ('wendy panuelos', 'Wendy Panuelos'),
         ('emir delos santos', 'Emir Delos Santos'), ('zack concepcion', 'Zack Concepcion'),
         ('mariebien custodio', 'Mariebien Custodio'), ('thea vivar', 'Thea Vivar'), ('lovely villafranca', 'Lovely Villafranca'),
         ('tamara bautista', 'Tamara Bautista'), ('mark elias gonzaga', 'Mark Elias Gonzaga'), ('support hiring', 'Support Hiring'),
         ('maximillian adrian christian venida', 'Maximillian Adrian Christian Venida'), ('grace_lu', 'Grace Lu'), ('gloc', 'GLOC'),
         ('patrick arandia', 'Patrick Arandia'), ('paula fernandez', 'Paula Kris Fernandez'),
         ('jorelle ardielle aborde', 'Jorelle Ardielle Aborde'), ('shyrelina jose', 'Shyrelina Jose'), ('jayvee quizon', 'Jayvee Quizon'),
         ('jester renz almadrigo', 'Jester Renz Almadrigo'), ('celeste mercado', 'Celeste Mercado'), ('alekcie vergara', 'Alekcie Vergara')],
        string="Requestor", related='department_id.x_requestor')
    x_requestor_support_hiring = fields.Selection(
        [('effy bongco', 'Effy Bongco'), ('mariebien custodio', 'Mariebien Custodio'), ('thea vivar', 'Thea Vivar'),
         ('tamara bautista', 'Tamara Bautista'), ('anju shilsky', 'Anju Shilsky'), ('peter lovell', 'Peter Lovell'),
         ('support hiring', 'Support Hiring'), ('myrtle_de_guzman', 'Myrtle De Guzman'),
         ('billy_espinosa', 'Billy Espinosa'),
         ('joey_plazo', 'Joey Plazo'),
         ('eidrian_santos', 'Eidrian Santos'),
         ('louie_lao', 'Louie Lao'),
         ('oliver_pietri', 'Oliver Pietri'),
         ('sandy_brady', 'Sandy Brady'),
         ('eljay_guiloreza', 'Eljay Guiloreza'),
         ('jl_lustre', 'JL Lustre')], string="Requestor", related='department_id.x_requestor_support_hiring')
    # x_job_str_category = fields.Char('Category', readonly=True, store=True)
    # x_job_str_requestor = fields.Char('Requestor', readonly=True, store=True)
    user_id = fields.Many2one('res.users', "Recruiter", tracking=True)
    x_department = fields.Char(string='For Position Code', readonly=True, related='department_id.name')
    x_industry = fields.Selection(
        [('back office', 'Back Office'), ('customer service', 'Customer Service'), ('digital', 'Digital'),
         ('finance', 'Finance'), ('medical', 'Medical'), ('operations support', 'Operations Support'),
         ('sales', 'Sales'), ('supply chain', 'Supply Chain'), ('tech', 'Tech')],
        string='Industry')
    

    _sql_constraints = [
        ('name_company_uniq', 'unique(name, company_id, department_id)',
         'The name of the job position must be unique per department in company!'),
        ('no_of_recruitment_positive', 'CHECK(no_of_recruitment >= 0)',
         'The expected number of new employees must be positive.')
    ]

    # Update Logs
    update_logs = fields.Text(string="Update Logs", store=True, default="")
    updated_by = fields.Text(string="Updated By", store=True, compute="_onchange_last_update")

    @api.onchange('name', 'department_id', 'x_requestor', 'x_industry', 'x_category', 'website_published',
                  'description', 'website_description')
    def _onchange_fields_update(self):
        # set timezone
        user_timezone = 'Asia/Singapore'
        utc_now = datetime.utcnow()
        # convert time
        user_timezone = pytz.timezone(user_timezone)
        user_time = utc_now.astimezone(user_timezone)

        # NAME
        if self._origin:  # check old value=
            if self.update_logs == False:
                self.update_logs = ""
            # Department NAME
            if self.name != self._origin.name:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Job Position: {self._origin.name} to {self.name}\n"
            # Category
            if self.department_id.name != self._origin.department_id.name:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Client Name: {self._origin.department_id.name} to {self.department_id.name}\n"
            # Requestor
            if self.x_requestor != self._origin.x_requestor:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Requestor: {self._origin.x_requestor} to {self.x_requestor}\n"
            # Category
            if self.x_category != self._origin.x_category:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Category: {self._origin.x_category} to {self.x_category}\n"
            # Industry
            if self.x_industry != self._origin.x_industry:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Industry: {self._origin.x_industry} to {self.x_industry}\n"
            # Published
            if self.website_published != self._origin.website_published:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Published the position\n"
            # Description
            if self.description != self._origin.description:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Updated the description\n"
            # Job Template Description
            if self.website_description != self._origin.website_description:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Updated the job template\n"

    @api.depends('write_uid')
    def _onchange_last_update(self):
        for rec in self:
            if rec.write_uid:
                if rec.updated_by != False:
                    rec.updated_by += f"Updated By: {self.write_uid.name}\n"
                else:
                    rec.updated_by = ""

    @api.depends('no_of_recruitment', 'employee_ids.job_id', 'employee_ids.active')
    def _compute_employees(self):
        employee_data = self.env['hr.employee']._read_group([('job_id', 'in', self.ids)], ['job_id'], ['job_id'])
        result = dict((data['job_id'][0], data['job_id_count']) for data in employee_data)
        for job in self:
            job.no_of_employee = result.get(job.id, 0)
            job.expected_employees = result.get(job.id, 0) + job.no_of_recruitment

    @api.model_create_multi
    def create(self, vals_list):
        """ We don't want the current user to be follower of all created job """
        return super(Job, self.with_context(mail_create_nosubscribe=True)).create(vals_list)

    @api.returns('self', lambda value: value.id)
    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        if 'name' not in default:
            default['name'] = _("%s (copy)") % (self.name)
        return super(Job, self).copy(default=default)

    def write(self, vals):
        if len(self) == 1:
            handle_history_divergence(self, 'description', vals)
        return super(Job, self).write(vals)
