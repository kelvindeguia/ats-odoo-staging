# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import datetime

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class Department(models.Model):
    _name = "hr.department"
    _description = "Department"
    _inherit = ['mail.thread']
    _order = "name"
    _rec_name = 'complete_name'
    _parent_store = True

    name = fields.Char('Department Name', required=True)
    complete_name = fields.Char('Complete Name', compute='_compute_complete_name', recursive=True, store=True)
    active = fields.Boolean('Active', default=True)
    company_id = fields.Many2one('res.company', string='Company', index=True, default=lambda self: self.env.company)
    parent_id = fields.Many2one('hr.department', string='Parent Department', index=True,
                                domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    child_ids = fields.One2many('hr.department', 'parent_id', string='Child Departments')
    manager_id = fields.Many2one('hr.employee', string='Manager', tracking=True,
                                 domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    member_ids = fields.One2many('hr.employee', 'department_id', string='Members', readonly=True)
    total_employee = fields.Integer(compute='_compute_total_employee', string='Total Employee')
    jobs_ids = fields.One2many('hr.job', 'department_id', string='Jobs')
    plan_ids = fields.One2many('hr.plan', 'department_id')
    plans_count = fields.Integer(compute='_compute_plan_count')
    note = fields.Text('Note')
    color = fields.Integer('Color Index')
    parent_path = fields.Char(index=True, unaccent=False)
    master_department_id = fields.Many2one(
        'hr.department', 'Master Department', compute='_compute_master_department_id', store=True)

    # Custom Fields
    job_id = fields.Many2one('hr.job')
    x_requestor = fields.Selection(
        [('effy bongco', 'Effy Bongco'), ('wendy panuelos', 'Wendy Panuelos'),
         ('emir delos santos', 'Emir Delos Santos'), ('zack concepcion', 'Zack Concepcion'),
         ('mariebien custodio', 'Mariebien Custodio'), ('thea vivar', 'Thea Vivar'), ('lovely villafranca', 'Lovely Villafranca'),
         ('tamara bautista', 'Tamara Bautista'), ('mark elias gonzaga', 'Mark Elias Gonzaga'), ('support hiring', 'Support Hiring'),
         ('maximillian adrian christian venida', 'Maximillian Adrian Christian Venida'), ('grace_lu', 'Grace Lu'), ('gloc', 'GLOC'),
         ('patrick arandia', 'Patrick Arandia'), ('paula fernandez', 'Paula Kris Fernandez'),
         ('jorelle ardielle aborde', 'Jorelle Ardielle Aborde'), ('shyrelina jose', 'Shyrelina Jose'), ('jayvee quizon', 'Jayvee Quizon'),
         ('jester renz almadrigo', 'Jester Renz Almadrigo'), ('celeste mercado', 'Celeste Mercado'), ('alekcie vergara', 'Alekcie Vergara')], string="Requestor",
        store=True)
    x_category = fields.Selection(
        [('client services', 'Client Services'), ('sales team', 'Sales Team'), ('support hiring', 'Support Hiring')],
        string="Category", store=True)
    x_requestor_support_hiring = fields.Selection(
        [('myrtle_de_guzman', 'Myrtle De Guzman'),
         ('billy_espinosa', 'Billy Espinosa'),
         ('joey_plazo', 'Joey Plazo'),
         ('eidrian_santos', 'Eidrian Santos'),
         ('louie_lao', 'Louie Lao'),
         ('oliver_pietri', 'Oliver Pietri'),
         ('sandy_brady', 'Sandy Brady'),
         ('eljay_guiloreza', 'Eljay Guiloreza'),
         ('jl_lustre', 'JL Lustre'),
         ], string="Department Head", store=True)
    x_requestor_final_str = fields.Char(string="Requestor Final Value", store=True)

    # Update Logs
    update_logs = fields.Text(string="Update Logs", store=True, default="")
    updated_by = fields.Text(string="Updated By", store=True, compute="_onchange_last_update")

    @api.onchange('name', 'x_category', 'x_requestor', 'x_requestor_support_hiring')
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
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Department Name: {self._origin.name} to {self.name}\n"
            # Category
            if self.x_category != self._origin.x_category:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Category: {self._origin.x_category} to {self.x_category}\n"
            # Requestor
            if self.x_requestor != self._origin.x_requestor:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Requestor: {self._origin.x_requestor} to {self.x_requestor}\n"
            # Department Head
            if self.x_requestor_support_hiring != self._origin.x_requestor_support_hiring:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Department Head: {self._origin.x_requestor_support_hiring} to {self.x_requestor_support_hiring}\n"

    @api.depends('write_uid')
    def _onchange_last_update(self):
        for rec in self:
            if rec.write_uid:
                if rec.updated_by != False:
                    rec.updated_by += f"Updated By: {self.write_uid.name}\n"
                else:
                    rec.updated_by = ""
            # if self._origin:
            # if self.updated_by == False:
            #     self.updated_by = ""
            # if self.write_uid != self._origin.write_uid:
            #     self.updated_by += f"Updated by {self.write_uid.name}\n"

    # @api.onchange('name', 'x_category', 'x_requestor','x_requestor_support_hiring')
    # def _onchange_fields(self):
    #     # set timezone
    #     user_timezone = 'Asia/Singapore'
    #     utc_now = datetime.utcnow()
    #     # convert time
    #     user_timezone = pytz.timezone(user_timezone)
    #     user_time = utc_now.astimezone(user_timezone)
    #
    #     # NAME
    #     if self._origin:  # check old value=
    #         if self.update_logs == False:
    #             self.update_logs = ""
    #         # Department NAME
    #         if self.name != self._origin.name:
    #             self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Department Name: {self._origin.name} to {self.name} by {self.write_uid.name}\n"
    #         # Category
    #         if self.x_category != self._origin.x_category:
    #             self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Category: {self._origin.x_category} to {self.x_category} by {self.write_uid.name}\n"
    #         # Requestor
    #         if self.x_requestor != self._origin.x_requestor:
    #             self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Requestor: {self._origin.x_requestor} to {self.x_requestor} by {self.write_uid.name}\n"# Requestor
    #         if self.x_requestor_support_hiring != self._origin.x_requestor_support_hiring:
    #             self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Requestor: {self._origin.x_requestor_support_hiring} to {self.x_requestor_support_hiring} by {self.write_uid.name}\n"
    # # Category
    # if self._origin:
    #     if self.x_category != self._origin.x_category:
    #         self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Category: {self._origin.x_category} to {self.x_category} by {self.write_uid.name}\n"
    # # Requestor
    # if self._origin:
    #     if self.x_requestor != self._origin.x_requestor:
    #         self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Requestor: {self._origin.x_requestor} to {self.x_requestor} by {self.write_uid.name}\n"

    @api.onchange('x_category')
    def _compute_clear_requestor(self):
        for rec in self:
            rec.x_requestor = False
            rec.x_requestor_support_hiring = False
            rec.x_requestor_final_str = ''

    @api.onchange('x_requestor_support_hiring')
    def onchange_x_requestor_support_hiring(self):
        for rec in self:
            if rec.x_category == 'support hiring':
                if self.x_requestor_support_hiring != False:
                    self.x_requestor_final_str = self.x_requestor_support_hiring
                    self.x_requestor_final_str = dict(
                        self.fields_get(allfields=['x_requestor_support_hiring'])['x_requestor_support_hiring'][
                            'selection'])[self.x_requestor_final_str]
                else:
                    self.x_requestor_final_str = ''

    @api.onchange('x_requestor')
    def onchange_x_requestor_value(self):
        for rec in self:
            if rec.x_category != 'support hiring':
                if self.x_requestor != False:
                    self.x_requestor_final_str = self.x_requestor
                    self.x_requestor_final_str = \
                        dict(self.fields_get(allfields=['x_requestor'])['x_requestor']['selection'])[
                            self.x_requestor]
                else:
                    self.x_requestor_final_str = ''

    def name_get(self):
        if not self.env.context.get('hierarchical_naming', True):
            return [(record.id, record.name) for record in self]
        return super(Department, self).name_get()

    @api.model
    def name_create(self, name):
        return self.create({'name': name}).name_get()[0]

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for department in self:
            if department.parent_id:
                department.complete_name = '%s / %s' % (department.parent_id.complete_name, department.name)
            else:
                department.complete_name = department.name

    @api.depends('parent_path')
    def _compute_master_department_id(self):
        for department in self:
            department.master_department_id = int(department.parent_path.split('/')[0])

    def _compute_total_employee(self):
        emp_data = self.env['hr.employee']._read_group([('department_id', 'in', self.ids)], ['department_id'],
                                                       ['department_id'])
        result = dict((data['department_id'][0], data['department_id_count']) for data in emp_data)
        for department in self:
            department.total_employee = result.get(department.id, 0)

    def _compute_plan_count(self):
        plans_data = self.env['hr.plan']._read_group([('department_id', 'in', self.ids)], ['department_id'],
                                                     ['department_id'])
        plans_count = {x['department_id'][0]: x['department_id_count'] for x in plans_data}
        for department in self:
            department.plans_count = plans_count.get(department.id, 0)

    @api.constrains('parent_id')
    def _check_parent_id(self):
        if not self._check_recursion():
            raise ValidationError(_('You cannot create recursive departments.'))

    @api.model_create_multi
    def create(self, vals_list):
        # TDE note: auto-subscription of manager done by hand, because currently
        # the tracking allows to track+subscribe fields linked to a res.user record
        # An update of the limited behavior should come, but not currently done.
        departments = super(Department, self.with_context(mail_create_nosubscribe=True)).create(vals_list)
        for department, vals in zip(departments, vals_list):
            manager = self.env['hr.employee'].browse(vals.get("manager_id"))
            if manager.user_id:
                department.message_subscribe(partner_ids=manager.user_id.partner_id.ids)
        return departments

    def write(self, vals):
        """ If updating manager of a department, we need to update all the employees
            of department hierarchy, and subscribe the new manager.
        """
        # TDE note: auto-subscription of manager done by hand, because currently
        # the tracking allows to track+subscribe fields linked to a res.user record
        # An update of the limited behavior should come, but not currently done.
        if 'manager_id' in vals:
            manager_id = vals.get("manager_id")
            if manager_id:
                manager = self.env['hr.employee'].browse(manager_id)
                # subscribe the manager user
                if manager.user_id:
                    self.message_subscribe(partner_ids=manager.user_id.partner_id.ids)
            # set the employees's parent to the new manager
            self._update_employee_manager(manager_id)
        return super(Department, self).write(vals)

    def _update_employee_manager(self, manager_id):
        employees = self.env['hr.employee']
        for department in self:
            employees = employees | self.env['hr.employee'].search([
                ('id', '!=', manager_id),
                ('department_id', '=', department.id),
                ('parent_id', '=', department.manager_id.id)
            ])
        employees.write({'parent_id': manager_id})

    def get_formview_action(self, access_uid=None):
        res = super().get_formview_action(access_uid=access_uid)
        if (not self.user_has_groups('hr.group_hr_user') and
                self.env.context.get('open_employees_kanban', False)):
            res.update({
                'name': self.name,
                'res_model': 'hr.employee.public',
                'view_type': 'kanban',
                'view_mode': 'kanban',
                'views': [(False, 'kanban'), (False, 'form')],
                'context': {'searchpanel_default_department_id': self.id},
                'res_id': False,
            })
        return res

    def action_plan_from_department(self):
        action = self.env['ir.actions.actions']._for_xml_id('hr.hr_plan_action')
        action['context'] = {'default_department_id': self.id, 'search_default_department_id': self.id}
        return action

    def get_children_department_ids(self):
        return self.env['hr.department'].search([('id', 'child_of', self.ids)])
