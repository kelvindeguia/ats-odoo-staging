# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from random import randint

from odoo import api, fields, models, tools, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError
from odoo.tools import Query
from odoo.tools.translate import _
import pandas as pd
import pytz
import numpy as np
import random
import string
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      
from dateutil.relativedelta import relativedelta
from datetime import datetime, date, timezone
from datetime import timedelta
from odoo.exceptions import ValidationError

from lxml import etree

AVAILABLE_PRIORITIES = [
    ('0', 'Normal'),
    ('1', 'Good'),
    ('2', 'Very Good'),
    ('3', 'Excellent')
]


class RecruitmentSource(models.Model):
    _name = "hr.recruitment.source"
    _description = "Source of Applicants"
    _inherit = ['utm.source.mixin']

    email = fields.Char(related='alias_id.display_name', string="Email", readonly=True)
    has_domain = fields.Char(compute='_compute_has_domain')
    job_id = fields.Many2one('hr.job', "Job", ondelete='cascade')
    alias_id = fields.Many2one('mail.alias', "Alias ID")
    medium_id = fields.Many2one('utm.medium', default=lambda self: self.env.ref('utm.utm_medium_website'))

    def _compute_has_domain(self):
        self.has_domain = bool(self.env["ir.config_parameter"].sudo().get_param("mail.catchall.domain"))

    def create_alias(self):
        campaign = self.env.ref('hr_recruitment.utm_campaign_job')
        medium = self.env.ref('utm.utm_medium_email')
        for source in self:
            vals = {
                'alias_parent_thread_id': source.job_id.id,
                'alias_model_id': self.env['ir.model']._get('hr.applicant').id,
                'alias_parent_model_id': self.env['ir.model']._get('hr.job').id,
                'alias_name': "%s+%s" % (source.job_id.alias_name or source.job_id.name, source.name),
                'alias_defaults': {
                    'job_id': source.job_id.id,
                    'campaign_id': campaign.id,
                    'medium_id': medium.id,
                    'source_id': source.source_id.id,
                },
            }
            source.alias_id = self.env['mail.alias'].create(vals)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'tree' and not bool(self.env["ir.config_parameter"].sudo().get_param("mail.catchall.domain")):
            email = arch.xpath("//field[@name='email']")[0]
            email.getparent().remove(email)
        return arch, view


class RecruitmentStage(models.Model):
    _name = "hr.recruitment.stage"
    _description = "Recruitment Stages"
    _order = 'sequence'

    name = fields.Char("Stage Name", required=True, translate=True)
    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    sequence = fields.Integer(
        "Sequence", default=10)
    job_ids = fields.Many2many(
        'hr.job', string='Job Specific',
        help='Specific jobs that uses this stage. Other jobs will not use this stage.')
    requirements = fields.Text("Requirements")
    template_id = fields.Many2one(
        'mail.template', "Email Template",
        help="If set, a message is posted on the applicant using the template when the applicant is set to the stage.")
    fold = fields.Boolean(
        "Folded in Kanban",
        help="This stage is folded in the kanban view when there are no records in that stage to display.")
    hired_stage = fields.Boolean('Hired Stage',
                                 help="If checked, this stage is used to determine the hire date of an applicant")
    legend_blocked = fields.Char(
        'Red Kanban Label', default=lambda self: _('Blocked'), translate=True, required=True)
    legend_done = fields.Char(
        'Green Kanban Label', default=lambda self: _('Ready for Next Stage'), translate=True, required=True)
    legend_normal = fields.Char(
        'Grey Kanban Label', default=lambda self: _('In Progress'), translate=True, required=True)
    is_warning_visible = fields.Boolean(compute='_compute_is_warning_visible')

    # Custom Fields
    x_application_stage_ownership = fields.Selection([('recruitment', 'Recruitment'), ('client', 'Client'), ('sourcing', 'Sourcing')],
                                                     'Application Stage Ownership', store=True)
    x_application_category = fields.Selection(
        [('active', 'Active'), ('failed', 'Failed'), ('pooling', 'Pooling'), ('inactive', 'Inactive'),
         ('job_offer', 'Job Offer'), ('neo', 'NEO')],
        'Application Category', store=True)
    lead_pipeline = fields.Boolean('Lead Pipeline', store=True)
    pipeline_count = fields.Boolean('Pipeline Count', store=True)

    @api.model
    def default_get(self, fields):
        if self._context and self._context.get('default_job_id') and not self._context.get('hr_recruitment_stage_mono',
                                                                                           False):
            context = dict(self._context)
            context.pop('default_job_id')
            self = self.with_context(context)
        return super(RecruitmentStage, self).default_get(fields)

    @api.depends('hired_stage')
    def _compute_is_warning_visible(self):
        applicant_data = self.env['hr.applicant']._read_group([('stage_id', 'in', self.ids)], ['stage_id'], 'stage_id')
        applicants = dict((data['stage_id'][0], data['stage_id_count']) for data in applicant_data)
        for stage in self:
            if stage._origin.hired_stage and not stage.hired_stage and applicants.get(stage._origin.id):
                stage.is_warning_visible = True
            else:
                stage.is_warning_visible = False


class RecruitmentDegree(models.Model):
    _name = "hr.recruitment.degree"
    _description = "Applicant Degree"
    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'The name of the Degree of Recruitment must be unique!')
    ]

    name = fields.Char("Degree Name", required=True, translate=True)
    sequence = fields.Integer("Sequence", default=1)


class Applicant(models.Model):
    _name = "hr.applicant"
    _description = "Applicant"
    _order = "priority desc, id desc"
    _inherit = ['mail.thread.cc', 'mail.activity.mixin', 'utm.mixin']
    _mailing_enabled = True
    _primary_email = 'email_from'
    _rec_name = 'partner_name'

    name = fields.Char("Subject / Application", help="Email subject for applications sent via email", tracking=True)
    # active = fields.Boolean("Active", default=True, tracking=True, groups='hr_recruitment.group_hr_recruitment_manager,hr_recruitment.group_hr_recruitment_delete_access',
    #                         help="If the active field is set to false, it will allow you to hide the case without removing it.")
    active = fields.Boolean("Active", default=True, tracking=True, help="If the active field is set to false, it will allow you to hide the case without removing it.")
    description = fields.Html("Description", tracking=True)
    email_from = fields.Char("Email", size=128, help="Applicant email", compute='_compute_partner_phone_email',
                             inverse='_inverse_partner_email', store=True, tracking=True)
    probability = fields.Float("Probability")
    partner_id = fields.Many2one('res.partner', "Contact", copy=False)
    create_date = fields.Datetime("Creation Date", readonly=True)
    stage_id = fields.Many2one('hr.recruitment.stage', 'Stage', ondelete='restrict',
                               compute='_compute_stage', store=True, readonly=False,
                               domain="['|', ('job_ids', '=', False), ('job_ids', '=', job_id)]",
                               copy=False, index=True,
                               group_expand='_read_group_stage_ids', tracking=True)
    last_stage_id = fields.Many2one('hr.recruitment.stage', "Last Stage",
                                    help="Stage of the applicant before being in the current stage. Used for lost cases analysis.")
    categ_ids = fields.Many2many('hr.applicant.category', string="Tags")
    company_id = fields.Many2one('res.company', "Company", compute='_compute_company', store=True, readonly=False,
                                 tracking=True)
    user_id = fields.Many2one(
        'res.users', "Recruiter", compute='_compute_user',
        domain="[('share', '=', False)]",
        tracking=True, store=True, readonly=False)
    date_closed = fields.Datetime("Hire Date", compute='_compute_date_closed', store=True, readonly=False,
                                  tracking=True)
    date_open = fields.Datetime("Assigned", readonly=True)
    date_last_stage_update = fields.Datetime("Last Stage Update", index=True, default=fields.Datetime.now)
    priority = fields.Selection(AVAILABLE_PRIORITIES, "Appreciation", default='0')
    job_id = fields.Many2one('hr.job', "Applied Job",
                             domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]", tracking=True,
                             index=True)
    salary_proposed_extra = fields.Char("Proposed Salary Extra",
                                        help="Salary Proposed by the Organisation, extra advantages", tracking=True,
                                        groups="hr_recruitment.group_hr_recruitment_user")
    salary_expected_extra = fields.Char("Expected Salary Extra", help="Salary Expected by Applicant, extra advantages",
                                        tracking=True, groups="hr_recruitment.group_hr_recruitment_user")
    salary_proposed = fields.Float("Proposed Salary", group_operator="avg", help="Salary Proposed by the Organisation",
                                   tracking=True, groups="hr_recruitment.group_hr_recruitment_user")
    salary_expected = fields.Float("Expected Salary", group_operator="avg", help="Salary Expected by Applicant",
                                   tracking=True, groups="hr_recruitment.group_hr_recruitment_user")
    availability = fields.Date("Availability",
                               help="The date at which the applicant will be available to start working", tracking=True)
    partner_name = fields.Char("Applicant's Name", tracking=True)
    partner_phone = fields.Char("Phone", size=32, compute='_compute_partner_phone_email',
                                inverse='_inverse_partner_phone', store=True)
    partner_mobile = fields.Char("Mobile", size=32, inverse='_inverse_partner_mobile', store=True)
    type_id = fields.Many2one('hr.recruitment.degree', "Degree", tracking=True)
    department_id = fields.Many2one(
        'hr.department', "Department", compute='_compute_department', store=True, readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]", tracking=True)
    day_open = fields.Float(compute='_compute_day', string="Days to Open", compute_sudo=True)
    day_close = fields.Float(compute='_compute_day', string="Days to Close", compute_sudo=True)
    delay_close = fields.Float(compute="_compute_day", string='Delay to Close', readonly=True, group_operator="avg",
                               help="Number of days to close", store=True)
    color = fields.Integer("Color Index", default=0)
    emp_id = fields.Many2one('hr.employee', string="Employee", help="Employee linked to the applicant.", copy=False)
    user_email = fields.Char(related='user_id.email', string="User Email", readonly=True)
    attachment_number = fields.Integer(compute='_get_attachment_number', string="Number of Attachments")
    employee_name = fields.Char(related='emp_id.name', string="Employee Name", readonly=False, tracking=False)
    attachment_ids = fields.One2many('ir.attachment', 'res_id', domain=[('res_model', '=', 'hr.applicant')],
                                     string='Attachments')
    kanban_state = fields.Selection([
        ('normal', 'Grey'),
        ('done', 'Green'),
        ('blocked', 'Red')], string='Kanban State',
        copy=False, default='normal', required=True)
    legend_blocked = fields.Char(related='stage_id.legend_blocked', string='Kanban Blocked')
    legend_done = fields.Char(related='stage_id.legend_done', string='Kanban Valid')
    legend_normal = fields.Char(related='stage_id.legend_normal', string='Kanban Ongoing')
    application_count = fields.Integer(compute='_compute_application_count',
                                       help='Applications with the same email or phone or mobile')
    refuse_reason_id = fields.Many2one('hr.applicant.refuse.reason', string='Refuse Reason', tracking=True)
    meeting_ids = fields.One2many('calendar.event', 'applicant_id', 'Meetings')
    meeting_display_text = fields.Char(compute='_compute_meeting_display')
    meeting_display_date = fields.Date(compute='_compute_meeting_display')
    # UTMs - enforcing the fact that we want to 'set null' when relation is unlinked
    campaign_id = fields.Many2one(ondelete='set null')
    medium_id = fields.Many2one(ondelete='set null')
    source_id = fields.Many2one(ondelete='set null')
    interviewer_ids = fields.Many2many('res.users', 'hr_applicant_res_users_interviewers_rel',
                                       string='Interviewers', index=True, tracking=True,
                                       domain="[('share', '=', False), ('company_ids', 'in', company_id)]")
    linkedin_profile = fields.Char('LinkedIn Profile', tracking=True)
    indeed_profile = fields.Char('Indeed Profile', tracking=True)
    jobstreet_profile = fields.Char('Jobstreet Profile', tracking=True)
    application_status = fields.Selection([
        ('ongoing', 'Ongoing'),
        ('hired', 'Hired'),
        ('refused', 'Refused'),
    ], compute="_compute_application_status")

    # QuickSight Fields
    qs_dept_name = fields.Char(string='QS Client Name', related='x_requisition_id.x_department_id.name', store=True)
    qs_job_title = fields.Char(string='QS Job Title', related='x_requisition_id.x_job_name.name', store=True)

    # Custom Fields
    # x_recruitment_manager = fields.Selection(
    #     [('erma_san_miguel', 'Erma San Miguel'), ('rodney ynares', 'Rodney Ynares'),
    #      ('alekcie vergara', 'Alekcie Vergara'), ('cesar jules van cayabat', 'Cesar Jules Van Cayabat'),
    #      ('erlyn ferrer', 'Erlyn Ferrer'), ('donna-lyn flores', 'Donna-lyn Flores'),
    #      ('ronald dayon dayon', 'Ronald Dayon Dayon')],
    #     string="Recruitment Manager", related='x_requisition_id.x_recruitment_manager', store=True)
    x_recruitment_manager = fields.Many2one('hr.recruitmentmanager', 'Recruitment Manager', related='x_requisition_id.x_recruitment_manager', store=True)
    x_requisition_id_name = fields.Char('Requisition ID', store=True, compute='_compute_x_requisition_id_name')
    x_mobile_number = fields.Char('Mobile Number')
    x_dept_name = fields.Char(string='Client Name', related='x_requisition_id.x_department_id.name')
    x_job_title_name = fields.Char(string='Job Title', readonly=True, related='x_requisition_id.x_job_name.name')
    x_requisition_id = fields.Many2one('hr.requisition', string='Requisition ID', store=True)
    x_resume = fields.Binary('CV', attachment=True, store=True)
    resume_file_name = fields.Char('CV File Name', store=True)
    # x_month = fields.Selection(
    #     [('january', 'January'), ('february', 'February'), ('march', 'March'), ('april', 'April'), ('may', 'May'),
    #      ('june', 'June'), ('july', 'July'), ('august', 'August'), ('september', 'September'), ('october', 'October'),
    #      ('november', 'November'), ('december', 'December')], string='Month', store=True)
    x_month = fields.Char(string='Month', store=True, compute='_compute_month')
    x_date_received = fields.Date(string='Date Received', store=True)
    x_application_category = fields.Selection(
        [('active', 'Active'), ('failed', 'Failed'), ('pooling', 'Pooling'), ('inactive', 'Inactive'),
         ('job_offer', 'Job Offer'), ('neo', 'NEO')],
        'Application Category',
        store=True)
    x_application_stage_ownership = fields.Selection([('recruitment', 'Recruitment'), ('client', 'Client'), ('sourcing', 'Sourcing')],
                                                     'Application Stage Ownership', store=True)
    x_application_stage_ownership2 = fields.Selection([('recruitment', 'Recruitment')],
                                                      'Application Stage Ownership', store=True)
    x_secondary_number = fields.Char(string='Secondary Mobile Number', store=True)
    x_referrer_name = fields.Char(string="Referrer's Name", store=True)
    x_job_classification = fields.Selection([('generic', 'Generic'), ('tech', 'Tech'), ('niche', 'Niche')],
                                            'Job Classification', store=True, related='x_requisition_id.x_job_classification')
    x_date_dispatched = fields.Date(string='Date Dispatched')
    x_days_aeging = fields.Integer(string='Days Ageing', compute='_compute_days_ageing')
    x_total_hiring_timeline = fields.Integer(string='Overall Hiring Timeline', compute='_compute_x_total_hiring_timeline')
    x_forecasted_start_date = fields.Date(string='Forecasted Start Date')
    x_status = fields.Many2many('hr.selectionstatus', string='Status')
    x_touch_date = fields.Date(string='Touch Date')
    x_touch_date_logs = fields.Text(string='Touch Date Logs', store=True)
    x_days_before_tapped = fields.Integer(string='Days Before Tapped', compute='_compute_x_days_before_tapped')
    stages_ids = fields.Many2many('hr.recruitment.stage', string='Stages')
    stages_text = fields.Char('Stages', store=True)
    reprofiled_identifier = fields.Boolean('Reprofiled?', store=True)
    sourcer_id = fields.Many2one('hr.sourcing', store=True)
    company = fields.Selection(
        [('aiic', ' ONSITE (ISUPPORT)'), ('iswerk', 'ONSITE (ISWERK)'), ('iswerk_hybrid', 'HYBRID (ISWERK)'), ('iswerk_wfh', 'WFH (ISWERK)')], string="Company",
        related="x_requisition_id.company", store=True)

    # CPS Related Fields
    x_cps_endorsement = fields.Date(string='CPS Date Endorsement')
    x_days_before_cps_endorsement = fields.Integer(string='Days Before Endorsed to CPS', compute='_compute_x_days_before_cps_endorsement')
    x_cps_result = fields.Selection([('passed', 'Passed'),('failed', 'Failed'), ('waiting for feedback','Awaiting Feedback')], 'CPS Result', store=True)
    x_cps_result_date = fields.Date(string='CPS Result Date')
    x_cps_days_before_result = fields.Integer(string='Days Before Result Was Given', compute='_compute_x_cps_days_before_result')

    # Client Interview Related Fields
    x_ci_date = fields.Date(string='Client Interview Date')
    x_days_before_ci_endorsement = fields.Integer(string='Days Before Scheduled to CI', compute='_compute_x_days_before_ci_endorsement')
    x_ci_result = fields.Selection(
        [('passed', 'Passed'), ('failed', 'Failed'), ('waiting for feedback', 'Awaiting Feedback')], 'Client Interview Result',
        store=True)
    x_ci_result_date = fields.Date(string='CI Result Date')
    x_ci_days_before_result = fields.Integer(string='Days Before CI Result', compute='_compute_x_ci_days_before_result')

    # Date Assessment Related Fields
    x_date_sent_assessment = fields.Date(string='Date Sent Assessment')
    x_da_days_before_result = fields.Integer(string='Days Before CI Result', compute='_compute_x_da_days_before_result')

    # Second Client Interview Related Fields
    x_second_ci_date = fields.Date(string='2nd Client Interview Date')
    x_days_before_second_ci_endorsement = fields.Integer(string='Days Before Scheduled to 2nd CI', compute='_compute_x_days_before_second_ci_endorsement')
    x_second_ci_result = fields.Selection(
        [('passed', 'Passed'), ('failed', 'Failed'), ('waiting for feedback', 'Awaiting Feedback')],
        '2nd Client Interview Result',
        store=True)
    x_second_ci_result_date = fields.Date(string='2nd CI Result Date')
    x_second_ci_days_before_result = fields.Integer(string='Days Before 2nd CI Result', compute='_compute_x_second_ci_days_before_result')

    # Third Client Interview Related Fields
    x_third_ci_date = fields.Date(string='3nd Client Interview Date')
    x_days_before_third_ci_endorsement = fields.Integer(string='Days Before Scheduled to 3nd CI', compute='_compute_x_days_before_third_ci_endorsement')
    x_third_ci_result = fields.Selection(
        [('passed', 'Passed'), ('failed', 'Failed'), ('waiting for feedback', 'Awaiting Feedback')],
        '3nd Client Interview Result',
        store=True)
    x_third_ci_result_date = fields.Date(string='3nd CI Result Date')
    x_third_ci_days_before_result = fields.Integer(string='Days Before 3nd CI Result', compute='_compute_x_third_ci_days_before_result')

    # Job Offer Related Fields
    x_jo_approval_date = fields.Date(string='Sent JO Approval Date')
    x_jo_discussion_date = fields.Date(string='JO Discussion Date')
    x_jo_revert_date = fields.Date(string='JO Revert Date')
    x_jo_status = fields.Selection(
        [('accepted', 'Accepted'), ('declined', 'Declined')],
        'JO Status',
        store=True)
    jo_declined_reason = fields.Selection(
        [('compensation', 'Compensation'), ('benefits', 'Benefits'), ('counter', 'Counter offered'),
         ('work_setup', 'Work setup preference(prefers WFH)'), ('health_issues', 'Health issues'),
         ('emergency', 'Emergency'), ('career_oals', 'Career Goals Alignment'),
         ('proximity', 'Proximity'), ('others', 'Others')],
        'JO Declined Reason',
        store=True)


    # NEO Related Fields
    x_neo_date = fields.Date(string='NEO Date')
    x_neo_status = fields.Selection(
        [('completed', 'Completed'), ('no-show', 'No-Show'), ('re-scheduled', 'Re-scheduled')],
        'NEO Status',
        store=True)

    # Specific Source
    x_app_specific_source_category = fields.Char('Source Category - Admin', store=True)
    x_app_source_category = fields.Selection(
        [('online-digital', 'Online-Digital'), ('proactive_search', 'Pro-active Search'),
         ('recruitment-marketing', 'Recruitment-Marketing'), ('employee referral', 'Employee Referral'),
         ('rehire', 'Rehire'), ('open house', 'Open House')],
        'Channel', store=True, tracking=True)
    x_app_specific_source_last = fields.Many2one('hr.specificsource', required=False, string='Specific Source',
                                                 domain="[('x_app_source_category','=','proactive_search')]",
                                                 store=True, tracking=True)
    x_app_specific_source_str = fields.Char('Specific Source', store=True)
    x_app_specific_source_last_str = fields.Char('String Source', store=True)
    x_app_specific_source1 = fields.Selection(
        [('indeed', 'Indeed'), ('linkedin', 'LinkedIn - Profile Search'), ('jobstreet', 'JobStreet - Resume Search'),
         ('applicant_referral', 'Applicant Referral'), ('facebook', 'Facebook')],
        'Specific Source', store=True)
    x_app_specific_source2 = fields.Selection(
        [('referral_program', 'Referral Program'), ('jobstreet_jobads', 'JobStreet - Job Ads'),
         ('facebook', 'Facebook'), ('careers_page', 'Careers Page/Portal'), ('apply_now', 'Apply Now'),
         ('client_referral', 'Client Referral'), ('tiktok', 'TikTok'), ('linkedin_jobads', 'LinkedIn - Job Ads')],
        'Specific Source', store=True)
    x_app_specific_source3 = fields.Selection(
        [('facebook', 'Facebook'), ('linkedin', 'LinkedIn')], 'Specific Source', store=True)
    attachment_size_limit = fields.Integer(default=8, string='Attachment Size Limit (in bytes)')
    x_employee_id = fields.Char('Employee ID')
    x_personal_email = fields.Char('Personal Email')
    x_employee_email = fields.Char('Employee Email')
    x_employee_account = fields.Char('Employee Account/Campaign')
    x_referral_position = fields.Char("Referral's Desired Position")
    x_proactive_search_checker = fields.Char('Source Checker', store=True)
    x_stage_reference = fields.Char('Stage Reference', related='stage_id.name')
    x_status_dropdown = fields.Many2one('hr.selectionstatus', 'Status')
    x_reprofile_logs = fields.Text('Re-profile Logs', readonly=True, store=True)
    x_reprofile_touch_date = fields.Date('Profile/Reprofile Touch Date', compute='_compute_x_requisition_id', store=True)
    update_logs = fields.Text('Fields Update Logs', store=True)
    channel_date_lodged = fields.Datetime('Channel Date Lodged', store=True, compute='_compute_channel_date_lodged')
    channel_days = fields.Integer('Channel Days', default=0, compute="_compute_channel_days")
    channel_days_ref = fields.Char('Channel Days Reference')
    date_today = fields.Datetime('Datetime Today', compute='_compute_date_today')
    ongoing_sourcing_date = fields.Date('Ongoing Sourcing Date', store=True, related='x_requisition_id.sourcing_date')
    position_classification = fields.Selection(
        [('growth', 'Growth'), ('new', 'New'), ('backfill', 'Backfill'), ('support hiring', 'Support Hiring')],
        string='Position Classification', store=True, related='x_requisition_id.x_req_position_classification')
    client_classification = fields.Selection(
        [('new', 'New'), ('existing', 'Existing'), ('sales', 'Sales'), ('support hiring', 'Support Hiring')],
        string='Client Classification', store=True, related='x_requisition_id.x_client_classification')

    # Referral fields
    employee_id = fields.Char('Employee ID', store=True)
    employee_email = fields.Char('Employee Email', store=True)
    employee_account = fields.Char('Employee Account/Program/Department', store=True)
    referral_position = fields.Char("Referral's Desired Position", store=True)
    referral_ids = fields.Many2many(comodel_name='ir.attachment',
                                    relation='m2m_ir_applicant_rel',
                                    column1='m2m_id',
                                    column2='attachment_id',
                                    string='Resume')
    applicant_url = fields.Text(string='Applicant URL', compute='_compute_url')
    profile_link = fields.Char('Profile Link', store=True)
    lead_pipeline_id = fields.Many2one('hr.recruitment.stage', 'Lead Pipeline', compute="_compute_pipeline_stage", store=True, domain="[('lead_pipeline', '=', True)]")
    pipeline_count_id = fields.Many2one('hr.recruitment.stage', 'Pipeline Count', compute="_compute_pipeline_count", store=True, domain="[('pipeline_count', '=', True)]")
    requisition_identifier_id = fields.Many2one('hr.requisition', string='Requisition Identifier', compute="_compute_requisition_identifier_id", store=True)
    active_file_stage_id = fields.Many2one('hr.pooling_stages', string='Active File Stage', tracking=True, store=True)
    stage_logs_ids = fields.One2many('hr.stagelogs', 'record_id', string='Stage Logs', store=True)
    stage_set_date = fields.Datetime('Stage Set Date', compute="_compute_stage_set_date", store=True)
    blacklisted = fields.Boolean('Blacklisted', store=True)

    # Additional Items
    reason_failed_interview_screening = fields.Text('Reason for Failed Client Interview or Screening', store=True)
    reason_reprofile = fields.Text('Reason for Reprofile', store=True)
    reason_neo_schedule_change = fields.Text('Reason for NEO Schedule Change', store=True)
    sourcer_name = fields.Char('Sourcer Name', store=True)
    survey_code = fields.Char(string='Survey Code', store=True, tracking=True)
    industry = fields.Selection(
        [('back office', 'Back Office'), ('customer service', 'Customer Service'), ('digital', 'Digital'),
         ('finance', "Finance"), ('medical', 'Medical'), ('operations support', 'Operations Support'),
         ('sales', 'Sales'), ('supply chain', 'Supply Chain'), ('tech', 'Tech')], 'Industry', related='x_requisition_id.x_industry', store=True)
    old_survey_code = fields.Char(string='Old Survey Code')
    date_survey_code_generated = fields.Datetime('Date Survey Code Generated', store=True, readonly=True)
    time_remaining = fields.Integer('Time Remaining', compute='_compute_time_remaining')
    time_remaining_reference = fields.Char('Time Remaining', store=True, readonly=True)
    touch_logs = fields.Text('Touch Logs', compute='_compute_log_touch', store=True)
    job_source = fields.Selection(
        [('careers_hub', 'Careers Hub'), ('jobstreet', 'Jobstreet')],
        string='Job Source', store=True)
    for_pooling = fields.Boolean('For Pooling', store=True)

    # Initial Touch Logs Fields
    initial_touch_date = fields.Date('Initial Touch Date', store=True)
    initial_touch_ageing = fields.Integer('Initial Touch to Movement Ageing', compute='_compute_initial_touch_ageing')
    initial_touch_ageing_ref = fields.Integer('Initial Touch to Movement Ageing Reference', store=True)
    
    @api.onchange('stage_id')
    def _onchange_initial_touch_date(self):
        for record in self:
            if record.stage_id:
                if record._origin.stage_id.name == "Untapped":
                    record.initial_touch_date = date.today()
            else:
                record.initial_touch_date = False

    @api.depends('initial_touch_date', 'x_touch_date')
    def _compute_initial_touch_ageing(self):
        for rec in self:
            if rec.initial_touch_date and rec.x_touch_date:
                # Ensure only date parts are compared (remove time components)
                initial_date = rec.initial_touch_date
                touch_date = rec.x_touch_date

                # Calculate the age in days excluding the same day
                if touch_date > initial_date:
                    age_timedelta = touch_date - initial_date

                    # Calculate the number of working days (excluding weekends)
                    total_days = age_timedelta.days
                    working_days = 0
                    current_date = initial_date + timedelta(days=1)  # Start from the next day

                    while current_date <= touch_date:
                        if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                            working_days += 1
                        current_date += timedelta(days=1)

                    rec.initial_touch_ageing = working_days
                    rec.initial_touch_ageing_ref = rec.initial_touch_ageing
                else:
                    rec.initial_touch_ageing = 0  # Set to 0 if it's the same day
                    rec.initial_touch_ageing_ref = rec.initial_touch_ageing
            else:
                rec.initial_touch_ageing = False
                rec.initial_touch_ageing_ref = rec.initial_touch_ageing
    
    def for_pooling_applicants(self):
        for rec in self:
            rec.for_pooling = True
    
    def unpool_applicants(self):
        for rec in self:
            rec.for_pooling = False

    # Candidate Form
    residing_metro_manila = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Are you currently residing within Metro Manila?', store=True)
    relocate = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='If not residing in Metro Manila, are you willing to relocate to Metro Manila for this position?', store=True)
    specification_ids = fields.Many2many('hr.specification', string='Do you have any specific or obligatory appointments in the next twelve (12) months? Please check all that apply:', store=True)
    appointments_specification = fields.Text('If you ticked any of the first five items, please specify details:', store=True)
    diagnosed = fields.Text('Have you been previously diagnosed with or treated for any medical condition, which, if left untreated, may adversely affect your ability to perform the duties and responsibilities attendant to the position for which you are applying? If so, please specify.', store=True)
    medical_condition = fields.Text('Do you presently have any medical condition, physical injury, impairment, or disability that may in any manner adversely affect your ability to adequately and satisfactorily perform the duties and responsibilities attendant to the position for which you are applying? If so, please specify.', store=True)
    
    @api.depends('partner_name', 'user_id', 'email_from', 'stage_id', 'x_mobile_number', 'x_resume', 'x_secondary_number', 'type_id', 'profile_link', 'x_requisition_id', 'x_app_source_category', 'x_app_specific_source_last', 'sourcer_id', 'x_application_category', 'x_application_stage_ownership', 'active_file_stage_id', 'x_status_dropdown', 'x_date_received', 'x_date_dispatched', 'x_touch_date', 'x_forecasted_start_date', 'description', 'reason_failed_interview_screening', 'reason_reprofile', 'reason_neo_schedule_change', 'x_cps_endorsement', 'x_cps_result', 'x_cps_result_date', 'x_ci_date', 'x_ci_result', 'x_ci_result_date', 'x_date_sent_assessment', 'x_second_ci_date', 'x_second_ci_result', 'x_second_ci_result_date', 'x_third_ci_date', 'x_third_ci_result', 'x_third_ci_result_date', 'x_jo_approval_date', 'x_jo_discussion_date', 'x_jo_revert_date', 'x_jo_status', 'jo_declined_reason', 'x_neo_date', 'x_neo_status')
    def _compute_log_touch(self):
        """Automatically logs touches when specified fields are changed."""
        user = self.env.user
        # set timezone
        user_timezone = 'Asia/Singapore'
        utc_now = datetime.utcnow()
        # convert time
        user_timezone = pytz.timezone(user_timezone)
        user_time = utc_now.astimezone(user_timezone)

        for record in self:
            log_entry = f"Touched by {user.name} on {user_time:%m/%d/%Y %I:%M%p}\n"
            if record.touch_logs:
                record.touch_logs += log_entry
            else:
                record.touch_logs = log_entry

    @api.depends('date_today')
    def _compute_time_remaining(self):
        for record in self:
            if record.date_today and record.date_survey_code_generated:
                time_diff = record.date_today - record.date_survey_code_generated
                
                # Subtract 30 minutes from the time difference
                adjusted_time_diff = timedelta(minutes=30) - time_diff
                
                # Calculate the remaining minutes
                minutes = max(0, adjusted_time_diff.total_seconds() // 60)
                record.time_remaining = minutes
                
                record.time_remaining_reference = record.time_remaining
                
                # If 30 minutes have passed or more
                # if minutes <= 0 and record.survey_code:
                #     if not record.old_survey_code:
                #         record.old_survey_code = record.survey_code
                #     record.survey_code = False
            else:
                record.time_remaining = 30
                record.old_survey_code = False

    # Survey Code Function
    def compute_random_code(self):
        for record in self:
            if record.partner_name:
                record.survey_code = self._generate_random_code_with_name(record.partner_name)
                record.date_survey_code_generated = record.date_today
            else:
                record.survey_code = self._generate_random_code()

    def _generate_random_code(self, length=8):
        # Generate a random code of specified length
        letters_and_digits = string.ascii_letters + string.digits
        return ''.join(random.choice(letters_and_digits) for i in range(length))

    def _generate_random_code_with_name(self, partner_name, length=8):
        # Replace spaces with underscores in the name
        name_with_underscores = partner_name.replace(' ', '_')
        # Include the name in the random code
        base_code = self._generate_random_code(length)
        return '{}-{}'.format(name_with_underscores, base_code)

    # blacklist function
    def blacklist_applicant(self):
        for record in self:
            record.sudo().write({'blacklisted': True})
            
            # Create a new hr.applicant record with the attachments transferred to the new referral_ids field
            new_applicant = self.env['hr.blacklist'].create({
                'name': record.partner_name,
                'email': record.email_from,
            })
        return True
    
    # Set stage date
    @api.depends('stage_id')
    def _compute_stage_set_date(self):
        for record in self:
            record.stage_set_date = record.date_today
    
    # Stage Logs
    @api.onchange('stage_id')
    def _stage_id_onchange_stage_logs(self):
        for record in self:
            if record.stage_id != record._origin.stage_id:
                new_log = self.env['hr.stagelogs'].create({
                    'ov_stage': record._origin.stage_id.name,
                    'nv_stage': record.stage_id.name,
                    'ov_datetime': record._origin.stage_set_date,
                    'nv_datetime': record.date_today,
                    'record_id': record.id,
                })
    
    @api.depends('x_requisition_id')
    def _compute_requisition_identifier_id(self):
        for record in self:
            if record.x_requisition_id:
                record.requisition_identifier_id = record.x_requisition_id

    # Auto compute of stage
    @api.depends('stage_id')
    def _compute_pipeline_stage(self):
        for record in self:
            if record.stage_id.name == "Untapped" or record.stage_id.name == "CBR" or record.stage_id.name == "Callback" or record.stage_id.name == "PKOR":
                  record.lead_pipeline_id = record.stage_id
            else:
                record.lead_pipeline_id = False   
                
    @api.depends('stage_id')
    def _compute_pipeline_count(self):
        for record in self:    
            if record.stage_id.name == "Passed: Active File" or record.stage_id.name == "Passed: Client Assessment" or record.stage_id.name == "Passed: Client Interview" or record.stage_id.name == "Passed: Endorsement" or record.stage_id.name == "Pending: Client Interview Feedback" or record.stage_id.name == "Pending: Client Interview Schedule" or record.stage_id.name == "Pending: Job Offer":
                  record.pipeline_count_id = record.stage_id
            else:
                record.pipeline_count_id = False

    # Disable referral creation on All Applications
    @api.constrains('x_app_source_category')
    def disable_employee_referral(self):
        for record in self:
            if record.x_app_source_category == 'employee referral':
                if not record.x_referrer_name:
                    raise ValidationError("You can't create a referral on this form.")
    
    # Record ageing
    # record_ageing = fields.Integer("Record Ageing", compute="_compute_record_ageing")
    record_ageing = fields.Integer("Record Ageing", compute="_compute_record_ageing")
    record_ageing_ref = fields.Integer('Record Ageing Reference', store=True)

    # Update Logs
    @api.onchange('sourcer_id','partner_name','email_from','resume_file_name','x_mobile_number','x_secondary_number',
                  'type_id','linkedin_profile','indeed_profile','jobstreet_profile','x_app_source_category',
                  'x_app_specific_source_last','x_referrer_name','user_id','x_application_stage_ownership',
                  'x_application_category','stage_id','x_status_dropdown','x_date_received','x_date_dispatched',
                  'x_forecasted_start_date','profile_link','active_file_stage_id', 'active')
    def _onchange_update_logs(self):
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
            # Applicant's Name
            if self.partner_name != self._origin.partner_name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Applicant's Name: {self._origin.partner_name} to {self.partner_name}\n\n"
            # Email
            if self.email_from != self._origin.email_from:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Email: {self._origin.email_from} to {self.email_from}\n\n"
            # Resume/CV
            if self.resume_file_name != self._origin.resume_file_name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | CV: {self._origin.resume_file_name} to {self.resume_file_name}\n\n"
            # Mobile Number
            if self.x_mobile_number != self._origin.x_mobile_number:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Mobile Number: {self._origin.x_mobile_number} to {self.x_mobile_number}\n\n"
            # Secondary Mobile Number
            if self.x_secondary_number != self._origin.x_secondary_number:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Secondary Mobile Number: {self._origin.x_secondary_number} to {self.x_secondary_number}\n\n"
            # Degree
            if self.type_id.name != self._origin.type_id.name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Degree: {self._origin.type_id.name} to {self.type_id.name}\n\n"
            # Linkedin Profile
            if self.linkedin_profile != self._origin.linkedin_profile:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Linkedin Profile: {self._origin.linkedin_profile} to {self.linkedin_profile}\n\n"
            # Indeed Profile
            if self.indeed_profile != self._origin.indeed_profile:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Indeed Profile: {self._origin.indeed_profile} to {self.indeed_profile}\n\n"
            # Jobstreet Profile
            if self.jobstreet_profile != self._origin.jobstreet_profile:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Jobstreet Profile: {self._origin.jobstreet_profile} to {self.jobstreet_profile}\n\n"
            # Channel
            if self.x_app_source_category != self._origin.x_app_source_category:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Channel: {self._origin.x_app_source_category} to {self.x_app_source_category}\n\n"
            # Specific Source
            if self.x_app_specific_source_last != self._origin.x_app_specific_source_last:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Specific Source: {self._origin.x_app_specific_source_last} to {self.x_app_specific_source_last}\n\n"
            # Referrer Name
            if self.x_referrer_name != self._origin.x_referrer_name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Referrer Name: {self._origin.x_referrer_name} to {self.x_referrer_name}\n\n"    
            # Recruiter
            if self.user_id.name != self._origin.user_id.name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Recruiter: {self._origin.user_id.name} to {self.user_id.name}\n\n"
            # Stage Owner
            if self.x_application_stage_ownership != self._origin.x_application_stage_ownership:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Stage Owner: {self._origin.x_application_stage_ownership} to {self.x_application_stage_ownership}\n\n"
            # Application Category
            if self.x_application_category != self._origin.x_application_category:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Application Category: {self._origin.x_application_category} to {self.x_application_category}\n\n"
            # Stage
            if self.stage_id.name != self._origin.stage_id.name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Stage: {self._origin.stage_id.name} to {self.stage_id.name}\n\n"
            # Status
            if self.x_status_dropdown != self._origin.x_status_dropdown:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Status: {self._origin.x_status_dropdown} to {self.x_status_dropdown}\n\n"
            # Date Received
            if self.x_date_received != self._origin.x_date_received:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Date Received: {self._origin.x_date_received} to {self.x_date_received}\n\n"
            # Date Dispatched
            if self.x_date_dispatched != self._origin.x_date_dispatched:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Date Dispatched: {self._origin.x_date_dispatched} to {self.x_date_dispatched}\n\n"      
            # Archive
            if self.active != self._origin.active:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Archive: {self._origin.active} to {self.active}\n\n"      
            # Forecasted Start Date
            if self.x_forecasted_start_date != self._origin.x_forecasted_start_date:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Forecasted Start Date: {self._origin.x_forecasted_start_date} to {self.x_forecasted_start_date}\n\n"               
             # Sourcer
            if self.sourcer_id.name != self._origin.sourcer_id.name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Recruiter: {self._origin.sourcer_id.name} to {self.sourcer_id.name}\n\n"

    # Reprofile Identifier
    @api.onchange('x_requisition_id')
    def onchange_reprofiled_identifier(self):
        for rec in self:
            rec.initial_touch_date = False
            rec.x_application_category = False
            rec.x_application_stage_ownership = False
            rec.stage_id = False
            if not self._origin.x_reprofile_logs == False:
                rec.reprofiled_identifier = True

    # Applicant Stage Funneling
    @api.onchange('stage_id')
    def onchange_stages_ids(self):
        # Replicate and add the selected value to the Many2many field
        if self.stage_id:
            self.stages_ids = [(4, self.stage_id.id)]
            self.stages_text = ', '.join(stage.name for stage in self.stages_ids)

    # Forecasted Start Date Fridays Input Only
    @staticmethod
    def is_friday(date):
        if date and date.weekday() == 4:
            return True
        return False

    @api.constrains('x_forecasted_start_date')
    def _check_friday_date(self):
        for record in self:
            if record.x_forecasted_start_date and not self.is_friday(record.x_forecasted_start_date):
                raise ValidationError("Forecasted Start Date must be a Friday.")

    # Record URL
    def _compute_url(self):
        # menu_id = self._context.get('menu_id', False)
        # base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        base_url = 'https://www.isw-hub.com/web#id=%d&cids=1&menu_id=182&action=248&model=%s&view_type=form' % (
        self.id, self._name)
        self.applicant_url = base_url

    # Channel Days Configurations
    @api.depends('date_today')
    def _compute_date_today(self):
        self.date_today = datetime.today()

    def _compute_record_ageing(self):
        for rec in self:
            if rec.create_date and rec.date_today:
                # Calculate the age in days
                age_timedelta = rec.date_today - rec.create_date

                # Calculate the number of working days (excluding weekends)
                total_days = age_timedelta.days
                working_days = 0
                initial_date = rec.create_date

                while initial_date <= rec.date_today:
                    if initial_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        working_days += 1
                    initial_date += timedelta(days=1)

                rec.record_ageing = working_days
                rec.record_ageing_ref = rec.record_ageing
            else:
                rec.record_ageing = False        

    @api.depends('date_today')
    def _compute_channel_days(self):
        for rec in self:
            if rec.channel_date_lodged:
                delta = rec.date_today - rec.channel_date_lodged
                days = delta.days
                rec.channel_days = days
                rec.channel_days_ref = rec.channel_days
            else:
                rec.channel_days = 0

    @api.depends('x_app_source_category')
    def _compute_channel_date_lodged(self):
        for rec in self:
            if rec.x_app_source_category:
                if rec.x_app_source_category == 'proactive_search':
                    rec.channel_date_lodged = datetime.utcnow()
                else:
                    rec.channel_date_lodged = False

    # Mobile number numerical values validation
    @api.onchange('x_mobile_number')
    def onchange_x_mobile_number(self):
        for rec in self:
            try:
                integer_value = int(rec.x_mobile_number)
            except ValueError:
                raise ValidationError('Please input numerical values only on mobile number field. (Avoid adding spaces or special values)')

    # Touch Date Logs
    @api.onchange('x_touch_date')
    def _onchange_x_touch_date_logs(self):
        # set timezone
        user_timezone = 'Asia/Singapore'
        utc_now = datetime.utcnow()
        # convert time
        user_timezone = pytz.timezone(user_timezone)
        user_time = utc_now.astimezone(user_timezone)

        # NAME
        if self._origin:  # check old value=
            if self.x_touch_date_logs == False:
                self.x_touch_date_logs = ""
            # Job Description
            if self.x_touch_date != self._origin.x_touch_date:
                self.x_touch_date_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Touch Date: {self._origin.x_touch_date} to {self.x_touch_date}\n"

    # Re-profile Logs
    @api.onchange('x_forecasted_start_date', 'x_requisition_id')
    def _onchange_x_reprofile_logs(self):
        # set timezone
        user_timezone = 'Asia/Singapore'
        utc_now = datetime.utcnow()
        # convert time
        user_timezone = pytz.timezone(user_timezone)
        user_time = utc_now.astimezone(user_timezone)

        # NAME
        if self._origin:  # check old value=
            if self.x_reprofile_logs == False:
                self.x_reprofile_logs = ""
            # Job Description
            if self.x_requisition_id.x_req_id != self._origin.x_requisition_id.x_req_id:
                self.x_reprofile_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Requisition ID: {self._origin.x_requisition_id.x_req_id} to {self.x_requisition_id.x_req_id}\n"

# Profile/Reprofile Touch Date
    @api.depends('x_requisition_id')
    def _compute_x_requisition_id(self):
        for rec in self:
            if rec.x_requisition_id:
                user_timezone = pytz.timezone('Asia/Singapore')
                # Get the current date and time in the user's time zone
                user_time = datetime.now(user_timezone)
                rec.x_reprofile_touch_date = user_time.date()

    # Get Recruitment Touch Date
    # @api.depends('__last_update')
    # def _compute_x_touch_date(self):
    #     if not self.x_touch_date:
    #         if self.message_ids:
    #             if self.message_ids.subtype_id.name != 'New Application':
    #                 print(self.message_ids.subtype_id)
    #                 user_timezone = pytz.timezone('Asia/Singapore')
    #                 # Get the current date and time in the user's time zone
    #                 user_time = datetime.now(user_timezone)
    #                 self.x_touch_date = user_time.date()

# NEO: Completed won't be able to be chosen upon creation
#     @api.onchange('stage_id')
#     def onchange_stage_if(self):
#         if self.stage_id:
#             if not self.message_ids:
#                 if self.x_stage_reference == 'NEO: Completed':
#                     raise ValidationError('You cannot choose "NEO: Completed" upon creation of application!')

# Proactive Search
    @api.onchange('x_app_specific_source_last')
    def _onchange_x_app_specific_source_last(self):
        for rec in self:
            if rec.x_app_specific_source_last:
                rec.x_app_specific_source_last_str = rec.x_app_specific_source_last.x_app_specific_source_new

    @api.onchange('x_app_specific_source_last', 'x_app_specific_source_str')
    def _onchange_x_proactive_search_checker(self):
        for rec in self:
            if rec.x_app_source_category:
                if rec.x_app_source_category == 'proactive_search':
                    if rec.x_app_specific_source_last_str == 'LinkedIn':
                        rec.x_proactive_search_checker = '1'
                    if rec.x_app_specific_source_last_str == 'Indeed':
                        rec.x_proactive_search_checker = '2'
                    if rec.x_app_specific_source_last_str == 'Jobstreet':
                        rec.x_proactive_search_checker = '3'
                    if rec.x_app_specific_source_last_str == 'Facebook' or rec.x_app_specific_source_last_str == False:
                        rec.x_proactive_search_checker = '0'
                if rec.x_app_source_category != 'proactive_search':
                    rec.x_proactive_search_checker = '0'
            if rec.x_app_source_category == False:
                rec.x_proactive_search_checker = '0'

# Disable Future Date Choosing
    @api.constrains('x_date_received', 'x_touch_date')
    def _check_future_date(self):
        for rec in self:
            # Set the user's time zone
            user_timezone = pytz.timezone('Asia/Singapore')

            # Get the current date and time in the user's time zone
            user_time = datetime.now(user_timezone)

            # Extract the date component from user_time
            user_date = user_time.date()
            if rec.x_date_received and rec.x_date_received > user_date or rec.x_touch_date and rec.x_touch_date > user_date:
                raise ValidationError("You can't select future dates!")

    # @api.onchange('x_requisition_id')
    # def onchange_x_test_department(self):
    #     self.x_dept_name = self.x_requisition_id.x_department_id.name
    #     self.x_job_title_name = self.x_requisition_id.x_job_name.name
    #     self.x_job_classification = self.x_requisition_id.x_job_classification

    # @api.constrains('x_resume')
    # def _check_attachment_size(self):
    #     for record in self:
    #         if record.x_resume:
    #             if len(record.x_resume) < record.attachment_size_limit:
    #                 raise models.ValidationError('File size exceeds the limit.')

    @api.constrains('email_from')
    def _email_validation(self):
        is_unique_email = self.search_count([('email_from', '=', self.email_from)])
        is_blacklisted_email = self.env['hr.blacklist'].search_count([('email', '=', self.email_from)])
        is_unique_email_referral = self.search_count([('email_from', '=', self.email_from), ('record_ageing_ref', '<', 90)])
        if self.email_from != False:
            if is_unique_email > 1 and self.employee_email == False:
                raise ValidationError(f"The provided email '{self.email_from}' was already used in an existing application. To avoid duplicate records, please provide a non-existent email.")
            if is_unique_email_referral and self.employee_email != False:
                raise ValidationError(
                    f"The provided email '{self.email_from}' was already used in an existing application. To avoid duplicate records, please provide a non-existent email or wait till the existing application turns 90 days.")
            if is_blacklisted_email:
                raise ValidationError(
                    f"The provided email '{self.email_from}' was already included among the blacklisted applicants.")

    @api.constrains('x_mobile_number')
    def _mobile_validation(self):
        is_unique = self.search_count([('x_mobile_number', '=', self.x_mobile_number)])
        is_unique_referral = self.search_count([('x_mobile_number', '=', self.x_mobile_number), ('record_ageing_ref', '<', 90)])
        if self.x_mobile_number != False:
            if is_unique > 1 and self.employee_email == False:
                raise ValidationError(
                    f"The provided primary mobile number '{self.x_mobile_number}' was already used in an existing application. To avoid duplicate records, please provide a non-existent mobile number.")
            if is_unique_referral and self.employee_email != False:
                raise ValidationError(
                    f"The provided primary mobile number '{self.x_mobile_number}' was already used in an existing application. To avoid duplicate records, please provide a non-existent mobile number or wait till the existing application turns 90 days.")
            for rec in self:
                if rec.x_mobile_number:
                    if len(rec.x_mobile_number) != 10:
                        raise ValidationError(_(f"'{self.x_mobile_number}' is not a valid mobile number."))
                    return True

    @api.depends('x_touch_date', 'x_jo_revert_date')
    def _compute_x_total_hiring_timeline(self):
        for record in self:
            if record.x_touch_date and record.x_jo_revert_date:
                start = fields.Date.from_string(record.x_touch_date)
                end = fields.Date.from_string(record.x_jo_revert_date)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_total_hiring_timeline = count
            else:
                record.x_total_hiring_timeline = 0

    @api.depends('x_third_ci_date', 'x_third_ci_result_date')
    def _compute_x_third_ci_days_before_result(self):
        for record in self:
            if record.x_third_ci_date and record.x_third_ci_result_date:
                start = fields.Date.from_string(record.x_third_ci_date)
                end = fields.Date.from_string(record.x_third_ci_result_date)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_third_ci_days_before_result = count
            else:
                record.x_third_ci_days_before_result = 0

    @api.depends('x_second_ci_result_date', 'x_third_ci_date')
    def _compute_x_days_before_third_ci_endorsement(self):
        for record in self:
            if record.x_second_ci_result_date and record.x_third_ci_date:
                start = fields.Date.from_string(record.x_second_ci_result_date)
                end = fields.Date.from_string(record.x_third_ci_date)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_days_before_third_ci_endorsement = count
            else:
                record.x_days_before_third_ci_endorsement = 0

    @api.depends('x_second_ci_date', 'x_second_ci_result_date')
    def _compute_x_second_ci_days_before_result(self):
        for record in self:
            if record.x_second_ci_date and record.x_second_ci_result_date:
                start = fields.Date.from_string(record.x_second_ci_date)
                end = fields.Date.from_string(record.x_second_ci_result_date)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_second_ci_days_before_result = count
            else:
                record.x_second_ci_days_before_result = 0

    @api.depends('x_date_sent_assessment', 'x_second_ci_date')
    def _compute_x_days_before_second_ci_endorsement(self):
        for record in self:
            if record.x_date_sent_assessment and record.x_second_ci_date:
                start = fields.Date.from_string(record.x_date_sent_assessment)
                end = fields.Date.from_string(record.x_second_ci_date)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_days_before_second_ci_endorsement = count
            else:
                record.x_days_before_second_ci_endorsement = 0

    @api.depends('x_ci_result_date', 'x_date_sent_assessment')
    def _compute_x_da_days_before_result(self):
        for record in self:
            if record.x_ci_result_date and record.x_date_sent_assessment:
                start = fields.Date.from_string(record.x_ci_result_date)
                end = fields.Date.from_string(record.x_date_sent_assessment)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_da_days_before_result = count
            else:
                record.x_da_days_before_result = 0

    @api.depends('x_ci_date', 'x_ci_result_date')
    def _compute_x_ci_days_before_result(self):
        for record in self:
            if record.x_ci_date and record.x_ci_result_date:
                start = fields.Date.from_string(record.x_ci_date)
                end = fields.Date.from_string(record.x_ci_result_date)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_ci_days_before_result = count
            else:
                record.x_ci_days_before_result = 0

    @api.depends('x_cps_result_date', 'x_ci_date')
    def _compute_x_days_before_ci_endorsement(self):
        for record in self:
            if record.x_cps_result_date and record.x_ci_date:
                start = fields.Date.from_string(record.x_cps_result_date)
                end = fields.Date.from_string(record.x_ci_date)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_days_before_ci_endorsement = count
            else:
                record.x_days_before_ci_endorsement = 0

    @api.depends('x_cps_endorsement', 'x_cps_result_date')
    def _compute_x_cps_days_before_result(self):
        for record in self:
            if record.x_cps_endorsement and record.x_cps_result_date:
                start = fields.Date.from_string(record.x_cps_endorsement)
                end = fields.Date.from_string(record.x_cps_result_date)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_cps_days_before_result = count
            else:
                record.x_cps_days_before_result = 0

    @api.depends('x_touch_date', 'x_cps_endorsement')
    def _compute_x_days_before_cps_endorsement(self):
        for record in self:
            if record.x_touch_date and record.x_cps_endorsement:
                start = fields.Date.from_string(record.x_touch_date)
                end = fields.Date.from_string(record.x_cps_endorsement)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_days_before_cps_endorsement = count
            else:
                record.x_days_before_cps_endorsement = 0

    @api.depends('x_date_dispatched', 'x_touch_date')
    def _compute_x_days_before_tapped(self):
        for record in self:
            if record.x_date_dispatched and record.x_touch_date:
                start = fields.Date.from_string(record.x_date_dispatched)
                end = fields.Date.from_string(record.x_touch_date)
                count = 0

                current_date = start
                while current_date <= end:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        count += 1
                    current_date += timedelta(days=1)

                record.x_days_before_tapped = count
            else:
                record.x_days_before_tapped = 0

    @api.depends('x_date_dispatched')
    def _compute_days_ageing(self):
        for rec in self:
            current_date = fields.Date.today()
            if rec.x_date_dispatched:
                date_difference = current_date - rec.x_date_dispatched
                x_days_aeging = 0
                for i in range(date_difference.days + 1):
                    date = current_date + timedelta(days=i)
                    if date.weekday() < 5:  # Monday to Friday (0-4)
                        x_days_aeging += 1
                rec.x_days_aeging = x_days_aeging
            else:
                rec.x_days_aeging = 0

    @api.depends('x_date_received')
    def _compute_month(self):
        for record in self:
            if record.x_date_received:
                x_month = fields.Date.from_string(record.x_date_received).strftime('%B')
                record.x_month = x_month
            else:
                record.x_month = False

    @api.depends('x_requisition_id')
    def _compute_x_requisition_id_name(self):
        for rec in self:
            rec.x_requisition_id_name = rec.x_requisition_id.x_req_id

    @api.onchange('x_application_category')
    def onchange_x_application_category(self):
        for rec in self:
            rec.x_application_stage_ownership = False
            rec.x_application_stage_ownership2 = False
            rec.stage_id = False

    @api.depends('x_application_category')
    def onchange_x_application_test(self):
        for rec in self:
            if rec.x_app_source_category == 'active':
                rec.x_application_stage_ownership = 'recruitment'

    @api.onchange('x_application_stage_ownership')
    def onchange_x_application_stage_ownership(self):
        for rec in self:
            rec.stage_id = False

    @api.onchange('x_application_stage_ownership2')
    def onchange_x_application_stage_ownership(self):
        for rec in self:
            rec.stage_id = False

    # Specific Source/Channel Functions
    @api.onchange('x_app_source_category')
    def onchange_x_clear_source_category(self):

        for rec in self:
            rec.x_app_specific_source3 = False
            rec.x_app_specific_source2 = False
            rec.x_app_specific_source1 = False
            rec.x_app_specific_source_str = ''
            rec.x_app_specific_source_last_str = ''
            rec.x_app_specific_source_last = False
            rec.x_proactive_search_checker = '0'
            rec.x_app_specific_source_category = rec.x_app_source_category
            # Display Employee Referral on Specific Source when the Channel is Employee Referral
            if rec.x_app_source_category == 'employee referral':
                specific_source = self.env['hr.specificsource'].search(
                    [('x_app_specific_source_new', '=', 'Employee Referral')], limit=1)
                rec.x_app_specific_source_last = specific_source.id if specific_source else False
            if rec.x_app_source_category == 'rehire':
                specific_source = self.env['hr.specificsource'].search(
                    [('x_app_specific_source_new', '=', 'Rehire')], limit=1)
                rec.x_app_specific_source_last = specific_source.id if specific_source else False
            if not rec.x_app_source_category == 'employee referral':
                rec.x_referrer_name = ''



    @api.onchange('x_app_specific_source3')
    def onchange_x_compute_specific_source2(self):
        for rec in self:
            if rec.x_app_source_category == 'recruitment-marketing':
                if self.x_app_specific_source3 != False:
                    self.x_app_specific_source_str = self.x_app_specific_source3
                    self.x_app_specific_source_str = \
                        dict(self.fields_get(allfields=['x_app_specific_source3'])['x_app_specific_source3'][
                                 'selection'])[
                            self.x_app_specific_source_str]
                else:
                    self.x_app_specific_source_str = ''

    @api.onchange('x_app_specific_source2')
    def onchange_x_compute_specific_source2(self):
        for rec in self:
            if rec.x_app_source_category == 'insourcing':
                if self.x_app_specific_source2 != False:
                    self.x_app_specific_source_str = self.x_app_specific_source2
                    self.x_app_specific_source_str = \
                        dict(self.fields_get(allfields=['x_app_specific_source2'])['x_app_specific_source2'][
                                 'selection'])[
                            self.x_app_specific_source_str]
                else:
                    self.x_app_specific_source_str = ''

    @api.onchange('x_app_specific_source1')
    def onchange_x_compute_specific_source1(self):
        for rec in self:
            if rec.x_app_source_category == 'proactive_search':
                if self.x_app_specific_source1 != False:
                    self.x_app_specific_source_str = self.x_app_specific_source1
                    self.x_app_specific_source_str = \
                        dict(self.fields_get(allfields=['x_app_specific_source1'])['x_app_specific_source1'][
                                 'selection'])[
                            self.x_app_specific_source_str]
                else:
                    self.x_app_specific_source_str = ''

    @api.onchange('job_id')
    def _onchange_job_id(self):
        for applicant in self:
            if applicant.job_id.name:
                applicant.name = applicant.job_id.name

    @api.depends('date_open', 'date_closed')
    def _compute_day(self):
        for applicant in self:
            if applicant.date_open:
                date_create = applicant.create_date
                date_open = applicant.date_open
                applicant.day_open = (date_open - date_create).total_seconds() / (24.0 * 3600)
            else:
                applicant.day_open = False
            if applicant.date_closed:
                date_create = applicant.create_date
                date_closed = applicant.date_closed
                applicant.day_close = (date_closed - date_create).total_seconds() / (24.0 * 3600)
                applicant.delay_close = applicant.day_close - applicant.day_open
            else:
                applicant.day_close = False
                applicant.delay_close = False

    @api.depends('email_from', 'partner_phone', 'partner_mobile')
    def _compute_application_count(self):
        self.flush_model(['email_from'])
        applicants = self.env['hr.applicant']
        for applicant in self:
            if applicant.email_from or applicant.partner_phone or applicant.partner_mobile:
                applicants |= applicant
        # Done via SQL since read_group does not support grouping by lowercase field
        if applicants.ids:
            query = Query(self.env.cr, self._table, self._table_query)
            query.add_where('hr_applicant.id in %s', [tuple(applicants.ids)])
            # Count into the companies that are selected from the multi-company widget
            company_ids = self.env.context.get('allowed_company_ids')
            if company_ids:
                query.add_where('other.company_id in %s', [tuple(company_ids)])
            self._apply_ir_rules(query)
            from_clause, where_clause, where_clause_params = query.get_sql()
            # In case the applicant phone or mobile is configured in wrong field
            query_str = """
            SELECT hr_applicant.id as appl_id,
                COUNT(other.id) as count
              FROM hr_applicant
              JOIN hr_applicant other ON LOWER(other.email_from) = LOWER(hr_applicant.email_from)
                OR other.partner_phone = hr_applicant.partner_phone OR other.partner_phone = hr_applicant.partner_mobile
                OR other.partner_mobile = hr_applicant.partner_mobile OR other.partner_mobile = hr_applicant.partner_phone
            %(where)s
        GROUP BY hr_applicant.id
            """ % {
                'where': ('WHERE %s' % where_clause) if where_clause else '',
            }
            self.env.cr.execute(query_str, where_clause_params)
            application_data_mapped = dict((data['appl_id'], data['count']) for data in self.env.cr.dictfetchall())
        else:
            application_data_mapped = dict()
        for applicant in applicants:
            applicant.application_count = application_data_mapped.get(applicant.id, 1) - 1
        (self - applicants).application_count = False

    @api.depends_context('lang')
    @api.depends('meeting_ids', 'meeting_ids.start')
    def _compute_meeting_display(self):
        applicant_with_meetings = self.filtered('meeting_ids')
        (self - applicant_with_meetings).update({
            'meeting_display_text': _('No Meeting'),
            'meeting_display_date': ''
        })
        today = fields.Date.today()
        for applicant in applicant_with_meetings:
            count = len(applicant.meeting_ids)
            dates = applicant.meeting_ids.mapped('start')
            min_date, max_date = min(dates).date(), max(dates).date()
            if min_date >= today:
                applicant.meeting_display_date = min_date
            else:
                applicant.meeting_display_date = max_date
            if count == 1:
                applicant.meeting_display_text = _('1 Meeting')
            elif applicant.meeting_display_date >= today:
                applicant.meeting_display_text = _('Next Meeting')
            else:
                applicant.meeting_display_text = _('Last Meeting')

    @api.depends('refuse_reason_id', 'date_closed')
    def _compute_application_status(self):
        for applicant in self:
            if applicant.refuse_reason_id:
                applicant.application_status = 'refused'
            elif applicant.date_closed:
                applicant.application_status = 'hired'
            else:
                applicant.application_status = 'ongoing'

    def _get_attachment_number(self):
        read_group_res = self.env['ir.attachment']._read_group(
            [('res_model', '=', 'hr.applicant'), ('res_id', 'in', self.ids)],
            ['res_id'], ['res_id'])
        attach_data = dict((res['res_id'], res['res_id_count']) for res in read_group_res)
        for record in self:
            record.attachment_number = attach_data.get(record.id, 0)

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        # retrieve job_id from the context and write the domain: ids + contextual columns (job or default)
        job_id = self._context.get('default_job_id')
        search_domain = [('job_ids', '=', False)]
        if job_id:
            search_domain = ['|', ('job_ids', '=', job_id)] + search_domain
        if stages:
            search_domain = ['|', ('id', 'in', stages.ids)] + search_domain

        stage_ids = stages._search(search_domain, order=order, access_rights_uid=SUPERUSER_ID)
        return stages.browse(stage_ids)

    @api.depends('job_id', 'department_id')
    def _compute_company(self):
        for applicant in self:
            company_id = False
            if applicant.department_id:
                company_id = applicant.department_id.company_id.id
            if not company_id and applicant.job_id:
                company_id = applicant.job_id.company_id.id
            applicant.company_id = company_id or self.env.company.id

    @api.depends('job_id')
    def _compute_department(self):
        for applicant in self:
            applicant.department_id = applicant.job_id.department_id.id

    @api.depends('job_id')
    def _compute_stage(self):
        for applicant in self:
            if applicant.job_id:
                if not applicant.stage_id:
                    stage_ids = self.env['hr.recruitment.stage'].search([
                        '|',
                        ('job_ids', '=', False),
                        ('job_ids', '=', applicant.job_id.id),
                        ('fold', '=', False)
                    ], order='sequence asc', limit=1).ids
                    applicant.stage_id = stage_ids[0] if stage_ids else False
            else:
                applicant.stage_id = False

    @api.depends('job_id')
    def _compute_user(self):
        for applicant in self:
            applicant.user_id = applicant.job_id.user_id.id or self.env.uid

    @api.depends('partner_id', 'partner_id.email', 'partner_id.mobile', 'partner_id.phone')
    def _compute_partner_phone_email(self):
        for applicant in self:
            applicant.partner_phone = applicant.partner_id.phone
            applicant.partner_mobile = applicant.partner_id.mobile
            applicant.email_from = applicant.partner_id.email

    def _inverse_partner_email(self):
        for applicant in self.filtered(lambda a: a.partner_id and a.email_from and not a.partner_id.email):
            applicant.partner_id.email = applicant.email_from

    def _inverse_partner_phone(self):
        for applicant in self.filtered(lambda a: a.partner_id and a.partner_phone and not a.partner_id.phone):
            applicant.partner_id.phone = applicant.partner_phone

    def _inverse_partner_mobile(self):
        for applicant in self.filtered(lambda a: a.partner_id and a.partner_mobile and not a.partner_id.mobile):
            applicant.partner_id.mobile = applicant.partner_mobile

    @api.depends('stage_id.hired_stage')
    def _compute_date_closed(self):
        for applicant in self:
            if applicant.stage_id and applicant.stage_id.hired_stage and not applicant.date_closed:
                applicant.date_closed = fields.datetime.now()
            if not applicant.stage_id.hired_stage:
                applicant.date_closed = False

    def _check_interviewer_access(self):
        if self.user_has_groups('hr_recruitment.group_hr_recruitment_interviewer'):
            raise AccessError(_('You are not allowed to perform this action.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('user_id'):
                vals['date_open'] = fields.Datetime.now()
            if vals.get('email_from'):
                vals['email_from'] = vals['email_from'].strip()
        applicants = super().create(vals_list)
        applicants.sudo().interviewer_ids._create_recruitment_interviewers()
        # Record creation through calendar, creates the calendar event directly, it will also create the activity.
        if 'default_activity_date_deadline' in self.env.context:
            deadline = fields.Datetime.to_datetime(self.env.context.get('default_activity_date_deadline'))
            category = self.env.ref('hr_recruitment.categ_meet_interview')
            for applicant in applicants:
                partners = applicant.partner_id | applicant.user_id.partner_id | applicant.department_id.manager_id.user_id.partner_id
                self.env['calendar.event'].sudo().with_context(default_applicant_id=applicant.id).create({
                    'applicant_id': applicant.id,
                    'partner_ids': [(6, 0, partners.ids)],
                    'user_id': self.env.uid,
                    'name': applicant.name,
                    'categ_ids': [category.id],
                    'start': deadline,
                    'stop': deadline + relativedelta(minutes=30),
                })
        return applicants

    def write(self, vals):
        # user_id change: update date_open
        if vals.get('user_id'):
            vals['date_open'] = fields.Datetime.now()
        if vals.get('email_from'):
            vals['email_from'] = vals['email_from'].strip()
        old_interviewers = self.interviewer_ids
        # stage_id: track last stage before update
        if 'stage_id' in vals:
            vals['date_last_stage_update'] = fields.Datetime.now()
            if 'kanban_state' not in vals:
                vals['kanban_state'] = 'normal'
            for applicant in self:
                vals['last_stage_id'] = applicant.stage_id.id
                res = super(Applicant, self).write(vals)
        else:
            res = super(Applicant, self).write(vals)
        if 'interviewer_ids' in vals:
            interviewers_to_clean = old_interviewers - self.interviewer_ids
            interviewers_to_clean._remove_recruitment_interviewers()
            self.sudo().interviewer_ids._create_recruitment_interviewers()
        if vals.get('emp_id'):
            self._update_employee_from_applicant()
        return res

    def get_empty_list_help(self, help):
        if 'active_id' in self.env.context and self.env.context.get('active_model') == 'hr.job':
            alias_id = self.env['hr.job'].browse(self.env.context['active_id']).alias_id
        else:
            alias_id = False

        nocontent_values = {
            'help_title': _('No application yet'),
            'para_1': _('Let people apply by email to save time.'),
            'para_2': _('Attachments, like resumes, get indexed automatically.'),
        }
        nocontent_body = """
            <p class="o_view_nocontent_empty_folder">%(help_title)s</p>
            <p>%(para_1)s<br/>%(para_2)s</p>"""

        if alias_id and alias_id.alias_domain and alias_id.alias_name:
            email = alias_id.display_name
            email_link = "<a href='mailto:%s'>%s</a>" % (email, email)
            nocontent_values['email_link'] = email_link
            nocontent_body += """<p class="o_copy_paste_email">%(email_link)s</p>"""

        return nocontent_body % nocontent_values

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        if view_type == 'form' and self.user_has_groups('hr_recruitment.group_hr_recruitment_interviewer'):
            view_id = self.env.ref('hr_recruitment.hr_applicant_view_form_interviewer').id
        return super().get_view(view_id, view_type, **options)

    def _notify_get_recipients(self, message, msg_vals, **kwargs):
        """
            Do not notify members of the Recruitment Interviewer group, as this
            might leak some data they shouldn't have access to.
        """
        recipients = super()._notify_get_recipients(message, msg_vals, **kwargs)
        interviewer_group = self.env.ref('hr_recruitment.group_hr_recruitment_interviewer').id
        return [recipient for recipient in recipients if interviewer_group not in recipient['groups']]

    def action_makeMeeting(self):
        """ This opens Meeting's calendar view to schedule meeting on current applicant
            @return: Dictionary value for created Meeting view
        """
        self.ensure_one()
        partners = self.partner_id | self.user_id.partner_id | self.department_id.manager_id.user_id.partner_id

        category = self.env.ref('hr_recruitment.categ_meet_interview')
        res = self.env['ir.actions.act_window']._for_xml_id('calendar.action_calendar_event')
        res['context'] = {
            'default_applicant_id': self.id,
            'default_partner_ids': partners.ids,
            'default_user_id': self.env.uid,
            'default_name': self.name,
            'default_categ_ids': category and [category.id] or False,
        }
        return res

    def action_open_attachments(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'name': _('Documents'),
            'context': {
                'default_res_model': 'hr.job',
                'default_res_id': self.ids[0],
                'show_partner_name': 1,
            },
            'view_mode': 'tree,form',
            'views': [
                (self.env.ref('hr_recruitment.ir_attachment_hr_recruitment_list_view').id, 'tree'),
                (False, 'form'),
            ],
            'search_view_id': self.env.ref('hr_recruitment.ir_attachment_view_search_inherit_hr_recruitment').ids,
            'domain': [('res_model', '=', 'hr.applicant'), ('res_id', 'in', self.ids), ],
        }

    def action_applications_email(self):
        self.ensure_one()
        self.env.cr.execute("""
        SELECT other.id
          FROM hr_applicant
          JOIN hr_applicant other ON LOWER(other.email_from) = LOWER(hr_applicant.email_from)
            OR other.partner_phone = hr_applicant.partner_phone OR other.partner_phone = hr_applicant.partner_mobile
            OR other.partner_mobile = hr_applicant.partner_mobile OR other.partner_mobile = hr_applicant.partner_phone
         WHERE hr_applicant.id in %s
        """, (tuple(self.ids),)
                            )
        ids = [res['id'] for res in self.env.cr.dictfetchall()]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Job Applications'),
            'res_model': self._name,
            'view_mode': 'tree,kanban,form,pivot,graph,calendar,activity',
            'domain': [('id', 'in', ids)],
            'context': {
                'active_test': False
            },
        }

    def action_open_employee(self):
        self.ensure_one()
        return {
            'name': _('Employee'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'view_mode': 'form',
            'res_id': self.emp_id.id,
        }

    def _track_template(self, changes):
        res = super(Applicant, self)._track_template(changes)
        applicant = self[0]
        if 'stage_id' in changes and applicant.stage_id.template_id:
            res['stage_id'] = (applicant.stage_id.template_id, {
                'auto_delete_message': True,
                'subtype_id': self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note'),
                'email_layout_xmlid': 'mail.mail_notification_light'
            })
        return res

    def _creation_subtype(self):
        return self.env.ref('hr_recruitment.mt_applicant_new')

    def _track_subtype(self, init_values):
        record = self[0]
        if 'stage_id' in init_values and record.stage_id:
            return self.env.ref('hr_recruitment.mt_applicant_stage_changed')
        return super(Applicant, self)._track_subtype(init_values)

    def _notify_get_reply_to(self, default=None):
        """ Override to set alias of applicants to their job definition if any. """
        aliases = self.mapped('job_id')._notify_get_reply_to(default=default)
        res = {app.id: aliases.get(app.job_id.id) for app in self}
        leftover = self.filtered(lambda rec: not rec.job_id)
        if leftover:
            res.update(super(Applicant, leftover)._notify_get_reply_to(default=default))
        return res

    def _message_get_suggested_recipients(self):
        recipients = super(Applicant, self)._message_get_suggested_recipients()
        for applicant in self:
            if applicant.partner_id:
                applicant._message_add_suggested_recipient(recipients, partner=applicant.partner_id.sudo(),
                                                           reason=_('Contact'))
            elif applicant.email_from:
                email_from = applicant.email_from
                if applicant.partner_name:
                    email_from = tools.formataddr((applicant.partner_name, email_from))
                applicant._message_add_suggested_recipient(recipients, email=email_from, reason=_('Contact Email'))
        return recipients

    def name_get(self):
        if self.env.context.get('show_partner_name'):
            return [
                (applicant.id, applicant.partner_name or applicant.name)
                for applicant in self
            ]
        return super().name_get()

    @api.model
    def message_new(self, msg, custom_values=None):
        """ Overrides mail_thread message_new that is called by the mailgateway
            through message_process.
            This override updates the document according to the email.
        """
        # remove default author when going through the mail gateway. Indeed we
        # do not want to explicitly set user_id to False; however we do not
        # want the gateway user to be responsible if no other responsible is
        # found.
        self = self.with_context(default_user_id=False)
        stage = False
        if custom_values and 'job_id' in custom_values:
            stage = self.env['hr.job'].browse(custom_values['job_id'])._get_first_stage()
        val = msg.get('from').split('<')[0]
        defaults = {
            'name': msg.get('subject') or _("No Subject"),
            'partner_name': val,
            'email_from': msg.get('from'),
            'partner_id': msg.get('author_id', False),
        }
        if msg.get('priority'):
            defaults['priority'] = msg.get('priority')
        if stage and stage.id:
            defaults['stage_id'] = stage.id
        if custom_values:
            defaults.update(custom_values)
        return super(Applicant, self).message_new(msg, custom_values=defaults)

    def _message_post_after_hook(self, message, msg_vals):
        if self.email_from and not self.partner_id:
            # we consider that posting a message with a specified recipient (not a follower, a specific one)
            # on a document without customer means that it was created through the chatter using
            # suggested recipients. This heuristic allows to avoid ugly hacks in JS.
            new_partner = message.partner_ids.filtered(lambda partner: partner.email == self.email_from)
            if new_partner:
                if new_partner.create_date.date() == fields.Date.today():
                    new_partner.write({
                        'type': 'private',
                        'phone': self.partner_phone,
                        'mobile': self.partner_mobile,
                    })
                self.search([
                    ('partner_id', '=', False),
                    ('email_from', '=', new_partner.email),
                    ('stage_id.fold', '=', False)]).write({'partner_id': new_partner.id})
        return super(Applicant, self)._message_post_after_hook(message, msg_vals)

    def create_employee_from_applicant(self):
        """ Create an employee from applicant """
        self.ensure_one()
        self._check_interviewer_access()

        contact_name = False
        if self.partner_id:
            address_id = self.partner_id.address_get(['contact'])['contact']
            contact_name = self.partner_id.display_name
        else:
            if not self.partner_name:
                raise UserError(_('You must define a Contact Name for this applicant.'))
            new_partner_id = self.env['res.partner'].create({
                'is_company': False,
                'type': 'private',
                'name': self.partner_name,
                'email': self.email_from,
                'mobile': self.x_mobile_number,
                'requisition id': self.x_requisition_id
            })
            self.partner_id = new_partner_id
            address_id = new_partner_id.address_get(['contact'])['contact']
        employee_data = {
            'default_name': self.partner_name or contact_name,
            'default_job_id': self.job_id.id,
            'default_job_title': self.job_id.name,
            'default_address_home_id': address_id,
            'default_department_id': self.department_id.id,
            'default_address_id': self.company_id.partner_id.id,
            'default_work_email': self.department_id.company_id.email or self.email_from,
            # To have a valid email address by default
            'default_work_phone': self.department_id.company_id.phone,
            'form_view_initial_mode': 'edit',
            'default_applicant_id': self.ids,
        }
        dict_act_window = self.env['ir.actions.act_window']._for_xml_id('hr.open_view_employee_list')
        dict_act_window['context'] = employee_data
        return dict_act_window

    def _update_employee_from_applicant(self):
        # This method is to be overriden
        return

    def archive_applicant(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refuse Reason'),
            'res_model': 'applicant.get.refuse.reason',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_applicant_ids': self.ids, 'active_test': False},
            'views': [[False, 'form']]
        }

    def reset_applicant(self):
        """ Reinsert the applicant into the recruitment pipe in the first stage"""
        default_stage = dict()
        for job_id in self.mapped('job_id'):
            default_stage[job_id.id] = self.env['hr.recruitment.stage'].search(
                ['|',
                 ('job_ids', '=', False),
                 ('job_ids', '=', job_id.id),
                 ('fold', '=', False)
                 ], order='sequence asc', limit=1).id
        for applicant in self:
            applicant.write(
                {'stage_id': applicant.job_id.id and default_stage[applicant.job_id.id],
                 'refuse_reason_id': False})

    # def toggle_active(self):
    #     res = super(Applicant, self).toggle_active()
    #     applicant_active = self.filtered(lambda applicant: applicant.active)
    #     if applicant_active:
    #         applicant_active.reset_applicant()
    #     applicant_inactive = self.filtered(lambda applicant: not applicant.active)
    #     if applicant_inactive:
    #         return applicant_inactive.archive_applicant()
    #     return res

    def action_send_email(self):
        return {
            'name': _('Send Email'),
            'type': 'ir.actions.act_window',
            'target': 'new',
            'view_mode': 'form',
            'res_model': 'applicant.send.mail',
            'context': {
                'default_applicant_ids': self.ids,
            }
        }

# Status Model
class SelectionStatus(models.Model):
    _name = "hr.selectionstatus"
    _description = 'Selection Status'
    _rec_name = 'x_status_name'

    x_status_name = fields.Char(string='Status Name')

# Specific Source Model
class SpecificSource(models.Model):
    _name = "hr.specificsource"
    _description = 'Specific Source'
    _rec_name = 'x_app_specific_source_new'

    x_app_specific_source_new = fields.Char('Specific Source', store=True)
    x_app_source_category = fields.Selection(
        [('online-digital', 'Online-Digital'), ('proactive_search', 'Pro-active Search'),
         ('recruitment-marketing', 'Recruitment-Marketing'), ('employee referral', 'Employee Referral'),
         ('rehire', 'Rehire'), ('open house', 'Open House')],
        'Channel', store=True)

class ApplicantCategory(models.Model):
    _name = "hr.applicant.category"
    _description = "Category of applicant"

    def _get_default_color(self):
        return randint(1, 11)

    name = fields.Char("Tag Name", required=True)
    color = fields.Integer(string='Color Index', default=_get_default_color)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', "Tag name already exists !"),
    ]


class ApplicantRefuseReason(models.Model):
    _name = "hr.applicant.refuse.reason"
    _description = 'Refuse Reason of Applicant'

    name = fields.Char('Description', required=True, translate=True)
    template_id = fields.Many2one('mail.template', string='Email Template', domain="[('model', '=', 'hr.applicant')]")
    active = fields.Boolean('Active', default=True)


class Requisition(models.Model):
    _name = "hr.requisition"
    _description = "Requisition"
    _rec_name = 'x_req_id'

    active = fields.Boolean("Active", default=True, help="If the active field is set to false, it will allow you to hide the case without removing it.")
    x_req_id = fields.Char('Requisition ID', store=True, readonly=True)
    x_department_id = fields.Many2one('hr.department', string='Client Name', store=True)
    x_job_name = fields.Many2one('hr.job', string='Job Title', store=True)
    # x_recruitment_manager = fields.Selection(
    #     [('erma_san_miguel', 'Erma San Miguel'), ('rodney ynares', 'Rodney Ynares'),
    #      ('alekcie vergara', 'Alekcie Vergara'), ('cesar jules van cayabat', 'Cesar Jules Van Cayabat'),
    #      ('erlyn ferrer', 'Erlyn Ferrer'), ('donna-lyn flores', 'Donna-lyn Flores'),
    #      ('ronald dayon dayon', 'Ronald Dayon Dayon')],
    #     string="Recruitment Manager", store=True)
    x_recruitment_manager = fields.Many2one('hr.recruitmentmanager', 'Recruitment Manager', store=True)
    # x_assigned_recruiter = fields.Selection(
    #     [('christian anonuevo', 'Christian Anonuevo'), ('paul anthony cruz', 'Paul Anthony Cruz'),
    #      ('nemuel pamplona', 'Nemuel Pamplona'), ('maurene garcia', 'Maurene Garcia'), ('ronald dayon dayon', 'Ronald Dayon Dayon'),
    #      ('charina juanitas', 'Charina Juanitas'), ('reina yago', 'Reina Yago'), ('vincent soriano', 'Vincent Soriano'), ('nicole tugangui', 'Nicole Tugangui')],
    #     string="Assigned Recruiter", store=True)
    x_remaining_vacancy = fields.Integer(string='Remaining Vacancy', store=True, compute='_compute_initial_vacancy')
    x_filled = fields.Integer(string='Filled', store=True)
    # x_no_of_demand = fields.Integer(string='Headcount Demand', store=True, related='x_job_name.no_of_recruitment')
    x_no_of_demand = fields.Integer(string='Headcount Demand', store=True)
    x_salary_package = fields.Char(string='Salary Package', store=True)
    x_hiring_manager = fields.Char(string='Hiring Manager', store=True)
    x_hiring_manager_email = fields.Char(string='Hiring Manager Email Address', store=True)
    x_calibration_call_availability = fields.Datetime(string='Calibration Availability for Calibration Call', store=True)
    x_recruitment_requestor = fields.Selection(
        [('effy bongco', 'Effy Bongco'), ('wendy panuelos', 'Wendy Panuelos'),
         ('emir delos santos', 'Emir Delos Santos'), ('zack concepcion', 'Zack Concepcion'),
         ('mariebien custodio', 'Mariebien Custodio'), ('thea vivar', 'Thea Vivar'), ('lovely villafranca', 'Lovely Villafranca'),
         ('tamara bautista', 'Tamara Bautista'), ('mark elias gonzaga', 'Mark Elias Gonzaga'), ('support hiring', 'Support Hiring'),
         ('maximillian adrian christian venida', 'Maximillian Adrian Christian Venida'), ('grace_lu', 'Grace Lu'), ('gloc', 'GLOC'),
         ('patrick arandia', 'Patrick Arandia'), ('paula fernandez', 'Paula Kris Fernandez'),
         ('jorelle ardielle aborde', 'Jorelle Ardielle Aborde'), ('shyrelina jose', 'Shyrelina Jose'), ('jayvee quizon', 'Jayvee Quizon'),
         ('jester renz almadrigo', 'Jester Renz Almadrigo'), ('celeste mercado', 'Celeste Mercado'), ('alekcie vergara', 'Alekcie Vergara')], string="Requestor",
        store=True)
    x_recruitment_support_team = fields.Char(string='Support Team', store=True)
    x_attachment_base = fields.Many2many(comodel_name="ir.attachment",
                                         relation="requisition_attachment",
                                         column1="req_id", column2="attachment_id", string="Attachment")
    x_calibration_notes = fields.Binary(string='Calibration Notes', attachment=True, store=True)
    calibration_notes_file_name = fields.Char('Calibration Notes File Name', store=True)
    x_job_description = fields.Binary(string='Job Description', attachment=True, store=True)
    job_description_file_name = fields.Char('Job Description File Name', store=True)
    x_client_classification = fields.Selection(
        [('new', 'New'), ('existing', 'Existing'), ('sales', 'Sales'), ('support hiring', 'Support Hiring')],
        string='Client Classification', store=True)
    x_requisition_status = fields.Selection(
        [('pending', 'For Calibration'),
         ('for pooling', 'For Pooling'),
         ('open', 'Open'),
         ('reopen', 'Reopened'),
         ('in progress', 'Ongoing Sourcing'),
         ('on hold', 'On Hold'),
         ('cancelled', 'Cancelled'),
         ('recalibrate', 'Recalibrate'),
         ('filled', 'Filled'),
         ('closed', 'Completed')],
        string='Requisition Status', default='pending', store=True)
    # x_requisition_status = fields.Selection(
    #     [('pending', 'Pending - For Calibration'),
    #      ('open', 'Open'),
    #      ('in progress', 'In Progress - Ongoing Sourcing'),
    #      ('on hold', 'On Hold'),
    #      ('cancelled', 'Cancelled'),
    #      ('closed', 'Closed - Completed')],
    #     string='Requisition Status', default='pending', store=True, compute='_set_closed_status')
    x_onhold_cancelled_remarks = fields.Text(string='Remarks', store=True)
    cancelled_reason = fields.Selection([('pro_active', 'Pro-Active'), ('abandoned', 'Abandoned')],
                                            'Cancelled Reason', store=True)
    x_req_sla = fields.Integer(string='Number of Days Passed', compute='_compute_difference')
    x_req_sla_total = fields.Integer(string='Number of Days Passed')
    x_date_today = fields.Datetime(string='Date Today', compute="_compute_x_date_today")
    x_onhold_days = fields.Integer(string='Onhold Days', store=True)
    x_onhold_start_date = fields.Datetime(string='Onhold Start Date', store=True)
    x_onhold_end_date = fields.Datetime(string='Onhold End Date', store=True)
    x_old_onhold_checker = fields.Integer(string='Old Onhold Checker', store=True)
    x_onhold_counter = fields.Integer(string='Onhold Counter')
    x_department_name = fields.Char(string='Client Name', related='x_department_id.name')
    x_requisition_url = fields.Text(string='Requisition URL', compute='_compute_url')
    x_onhold_logs = fields.Text(string='Onhold Logs', store=True)
    x_applicants_id = fields.Many2one('hr.applicant', string='Applications', store=True)
    x_days_passed = fields.Selection(
        [('less_than_30_days', 'Less than 30 days'), ('passed_30_days', 'Passed 30 days')], 'Days Passed', store=True, compute='_set_x_req_days_passed')
    x_job_classification = fields.Selection([('generic', 'Generic'), ('tech', 'Tech'), ('niche', 'Niche'), ('executive', 'Executive')],
                                            'Job Classification', store=True)
    x_industry = fields.Selection(
        [('back office', 'Back Office'), ('customer service', 'Customer Service'), ('digital', 'Digital'),
         ('finance', "Finance"), ('medical', 'Medical'), ('operations support', 'Operations Support'),
         ('sales', 'Sales'), ('supply chain', 'Supply Chain'), ('tech', 'Tech')], 'Industry', store=True)
    x_req_position_classification = fields.Selection(
        [('growth', 'Growth'), ('new', 'New'), ('backfill', 'Backfill'), ('support hiring', 'Support Hiring')],
        string='Position Classification', store=True)
    x_date_opened = fields.Char('Ongoing Sourcing Date', compute='_compute_date_opened', store=True)
    sourcing_date = fields.Date('Ongoing Sourcing Date', store=True)
    ongoing_sourcing_date = fields.Datetime('New Ongoing Sourcing Date', store=True)
    calibration_date = fields.Date(string='Calibration Date', store=True)
    company = fields.Selection(
        [('aiic', ' ONSITE (ISUPPORT)'), ('iswerk', 'ONSITE (ISWERK)'), ('iswerk_hybrid', 'HYBRID (ISWERK)'), ('iswerk_wfh', 'WFH (ISWERK)')], string="Company",
        store=True)
    start_date = fields.Date(string='Target Start Date', store=True)
    applicant_ids = fields.One2many('hr.applicant', 'x_requisition_id', 'Applicants', store=True)

    # QuickSight Fields
    qs_department_name = fields.Char(string='QS Client Name', related='x_department_id.name', store=True)
    qs_job_title = fields.Char(string='QS Job Title', related='x_job_name.name', store=True)

    # TA Live File Additional Fields
    career_level = fields.Selection([('rank_and_file', 'Rank and File'), ('managerial', 'Managerial'), ('executive', 'Executive')], string="Career Level", store=True)
    date_cancelled = fields.Datetime('Date Cancelled', compute="_compute_x_requisition_status", store=True)
    date_onhold = fields.Datetime('Date Onhold', compute="_compute_x_requisition_status", store=True)
    date_filled = fields.Datetime('Date Filled', compute="_compute_x_requisition_status", store=True)
    date_completed = fields.Datetime('Date Completed', compute="_compute_x_requisition_status", store=True)
    date_reopen = fields.Datetime('Date Reopen', compute="_compute_x_requisition_status", store=True)
    audio_clip_needed = fields.Boolean('Audio Clip Needed?', store=True)
    assessment_needed = fields.Boolean('Assessment Needed?', store=True)
    projected_headcount = fields.Integer('Projected Headcount to Close', store=True)
    projected_neo_date = fields.Date('Projected NEO Date', store=True)
    requisition_remarks = fields.Html('Requisition Remarks', store=True)
    sla_met = fields.Selection([('no', 'No'), ('yes', 'Yes')], 'SLA Met?', compute="_compute_sla_met", store=True)
    days_to_fill = fields.Integer('Days to Fill', compute="_compute_days_to_fill", store=True)
    priority = fields.Selection([('no','No'),('yes','Yes')], string="Priority", store=True)
    assigned_recruiter_id = fields.Many2one('hr.recruiter', 'Assigned Recruiter', store=True)
    client_website = fields.Char('Client Website', store=True)
    # secondary_hiring_manager_poc = fields.Char('Secondary Hiring POC', store=True)
    
    #New SLA Fields
    req_ageing = fields.Integer('Requisition Ageing', compute="_compute_new_sla")
    req_ageing_total = fields.Integer('Requisition Ageing')
    days_onhold = fields.Integer('Total Days Onhold', store=True)
    hold_start_date = fields.Datetime(string='New Onhold Start Date', store=True)
    hold_end_date = fields.Datetime(string='New Onhold End Date', store=True)
    old_onhold_checker = fields.Integer(string='New Old Onhold Checker', store=True)
    onhold_counter = fields.Integer(string='New Onhold Counter')
    end_date = fields.Datetime('New End Date', store=True)
    
    # Additional Items
    sec_hiring_manager = fields.Char(string='Secondary Hiring Manager POC', store=True)
    calibration_needed = fields.Boolean('Calibration Needed?', store=True)
    # field_test_boolean = fields.Boolean('Field Test Boolean', store=True)

    # Set to priority function
    def priority_records_requisition(self):
        for record in self:
            record.write({'priority': 'yes'})
    
    # Set to unpriority function
    def unpriority_records_requisition(self):
        for record in self:
            record.write({'priority': 'no'})
    
    # Getting applicant records function
    def compute_hired_applicants(self):
        for requisition in self:
            requisition.applicant_ids = self.env['hr.applicant'].search([('requisition_identifier_id', '=', requisition.id),'|', ('stage_id', '=', 'Signed: Job Offer'), ('x_jo_status', '=', 'accepted')])
    
    def compute_all_applicants(self):
        for requisition in self:
            requisition.applicant_ids = self.env['hr.applicant'].search([('requisition_identifier_id.x_req_id', '=', requisition.x_req_id)])

    @api.depends('date_filled')
    def _compute_sla_met(self):
        for record in self:
            if record.x_requisition_status == 'filled' or record.x_requisition_status == 'closed':
                if record.x_job_classification == 'generic':
                    if record.days_to_fill <= 30:
                        record.sla_met = 'yes'
                    else:
                        record.sla_met = 'no'    
                if record.x_job_classification == 'niche':
                    if record.days_to_fill <= 45:
                        record.sla_met = 'yes'
                    else:
                        record.sla_met = 'no'        
                if record.x_job_classification == 'tech':
                    if record.days_to_fill <= 60:
                        record.sla_met = 'yes'
                    else:
                        record.sla_met = 'no'        
                if record.x_job_classification == 'executive':
                    if record.days_to_fill <= 90:
                        record.sla_met = 'yes'
                    else:
                        record.sla_met = 'no'        

    @api.depends('date_filled')
    def _compute_days_to_fill(self):
        for record in self:
            filled_date = record.date_filled
            if record.date_filled == False:
                record.days_to_fill = 0
            if record.x_requisition_status == 'filled' or record.x_requisition_status == 'closed':
                date_difference = filled_date.date() - record.sourcing_date
                days_aeging = 0
                for i in range(date_difference.days + 1):
                    date = filled_date + timedelta(days=i)
                    if date.weekday() < 5:  # Monday to Friday (0-4)
                        days_aeging += 1
                record.days_to_fill = days_aeging
            else:
                record.days_to_fill = 0

    @api.depends('x_requisition_status')
    def _compute_x_requisition_status(self):
        for record in self:
            if record.x_requisition_status == 'cancelled':
                record.date_cancelled = record.x_date_today
            if record.x_requisition_status == 'on hold':
                record.date_onhold = record.x_date_today
            if record.x_requisition_status == 'filled':
                record.date_filled = record.x_date_today
            if record.x_requisition_status == 'closed':
                record.date_completed = record.x_date_today
            if record.x_requisition_status == 'reopen':
                record.date_reopen = record.x_date_today
    
    # Date Opened Function
    @api.depends('x_requisition_status')
    def _compute_date_opened(self):
        for rec in self:
            user_timezone = pytz.timezone('Asia/Singapore')
            # Get the current date and time in the user's time zone
            user_time = datetime.now(user_timezone)
            formatted_date = user_time.strftime('%m/%d/%Y %H:%M:%S')
            if rec.x_requisition_status == 'pending':
                rec.x_date_opened = formatted_date

    # @api.model
    # def fields_get(self, allfields=None, attributes=None):
    #     hide = ['x_onhold_days', 'x_onhold_start_date', 'x_onhold_end_date','x_old_onhold_checker','x_onhold_counter','x_department_name']
    #     res = super(Requisition, self).fields_get()
    #     for field in hide:
    #         res[field]['searchable'] = False
    #     return res

    # Update Logs
    update_logs = fields.Text(string="Update Logs", store=True, default="")
    updated_by = fields.Text(string="Updated By", store=True, compute="_onchange_last_update")

    @api.onchange('x_job_name', 'x_department_id', 'x_recruitment_requestor', 'x_calibration_call_availability',
                  'x_no_of_demand', 'x_req_position_classification', 'x_client_classification', 'x_job_classification',
                  'calibration_date', 'start_date', 'x_industry', 'company', 'x_requisition_status', 'sourcing_date', 'x_salary_package', 
                  'x_hiring_manager', 'x_hiring_manager_email', 'assigned_recruiter_id', 'career_level',
                  'audio_clip_needed', 'assessment_needed', 'projected_headcount', 'projected_neo_date', 'requisition_remarks',
                  'priority', 'active', 'x_recruitment_manager')
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
            # Job Title
            if self.x_job_name.name != self._origin.x_job_name.name:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Job Position: {self._origin.x_job_name.name} to {self.x_job_name.name} \n"
            # Client Name
            if self.x_department_id.name != self._origin.x_department_id.name:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Client Name: {self._origin.x_department_id.name} to {self.x_department_id.name}\n"
            # # Job Description
            # if self.x_job_description != self._origin.x_job_description:
            #     self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Job Description: {self._origin.x_job_description} to {self.x_job_description}\n"
            # Calibration Notes
            # if self.x_calibration_notes != self._origin.x_calibration_notes:
            #     self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Calibration Notes: {self._origin.x_calibration_notes} to {self.x_calibration_notes}\n"
            # Requestor
            if self.x_recruitment_requestor != self._origin.x_recruitment_requestor:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Requestor: {self._origin.x_recruitment_requestor} to {self.x_recruitment_requestor}\n"
            # Calibration Availability for Calibration Call
            if self.x_calibration_call_availability != self._origin.x_calibration_call_availability:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Calibration Availability for Calibration Call: {self._origin.x_calibration_call_availability} to {self.x_calibration_call_availability}\n"
            # Headcount Demand
            if self.x_no_of_demand != self._origin.x_no_of_demand:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Headcount Demand: {self._origin.x_no_of_demand} to {self.x_no_of_demand}\n"
            # Filled
            if self.x_filled != self._origin.x_filled:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Filled: {self._origin.x_filled} to {self.x_filled}\n"    
            # Calibration Date
            if self.calibration_date != self._origin.calibration_date:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Calibration Date: {self._origin.calibration_date} to {self.calibration_date}\n"
            # Archive
            if self.active != self._origin.active:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Archive: {self._origin.active} to {self.active}\n"
            # Start Date
            if self.start_date != self._origin.start_date:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Start Date: {self._origin.start_date} to {self.start_date}\n"   
            # Client Classification
            if self.x_client_classification != self._origin.x_client_classification:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Client Classification: {self._origin.x_client_classification} to {self.x_client_classification}\n"    
            # Job Classification
            if self.x_job_classification != self._origin.x_job_classification:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Job Classification: {self._origin.x_job_classification} to {self.x_job_classification}\n"
            # Position Classification
            if self.x_req_position_classification != self._origin.x_req_position_classification:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Position Classification: {self._origin.x_req_position_classification} to {self.x_req_position_classification}\n"
            # Industry
            if self.x_industry != self._origin.x_industry:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Industry: {self._origin.x_industry} to {self.x_industry}\n"
            # Company
            if self.company != self._origin.company:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Company: {self._origin.company} to {self.company}\n"
            # Requisition Status
            if self.x_requisition_status != self._origin.x_requisition_status:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Requisition Status: {self._origin.x_requisition_status} to {self.x_requisition_status}\n"
            # Ongoing Sourcing Date
            if self.sourcing_date != self._origin.sourcing_date:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Ongoing Sourcing Date: {self._origin.sourcing_date} to {self.sourcing_date}\n"    
            # Salary Package
            if self.x_salary_package != self._origin.x_salary_package:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Salary Package: {self._origin.x_salary_package} to {self.x_salary_package}\n"       
            # Hiring Manager
            if self.x_hiring_manager != self._origin.x_hiring_manager:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Hiring Manager: {self._origin.x_hiring_manager} to {self.x_hiring_manager}\n"
            # Hiring Manager Email Address
            if self.x_hiring_manager_email != self._origin.x_hiring_manager_email:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Hiring Manager Email Address: {self._origin.x_hiring_manager_email} to {self.x_hiring_manager_email}\n"
            # Recruitment Manager
            if self.x_recruitment_manager != self._origin.x_recruitment_manager:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Recruitment Manager: {self._origin.x_recruitment_manager} to {self.x_recruitment_manager}\n"
            # Assigned Recruiter
            if self.assigned_recruiter_id.name != self._origin.assigned_recruiter_id.name:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Assigned Recruiter: {self._origin.assigned_recruiter_id.name} to {self.assigned_recruiter_id.name}\n"
            # Career Level
            if self.career_level != self._origin.career_level:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Career Level: {self._origin.career_level} to {self.career_level}\n"
            # Audio Clip Needed
            if self.audio_clip_needed != self._origin.audio_clip_needed:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Audio Clip Needed: {self._origin.audio_clip_needed} to {self.audio_clip_needed}\n"
            # Assessment Needed
            if self.assessment_needed != self._origin.assessment_needed:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Assessment Needed: {self._origin.assessment_needed} to {self.assessment_needed}\n"
            # Projected Headcount to Close
            if self.projected_headcount != self._origin.projected_headcount:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Projected Headcount to Close: {self._origin.projected_headcount} to {self.projected_headcount}\n"
            # Projected NEO Date
            if self.projected_neo_date != self._origin.projected_neo_date:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Projected NEO Date: {self._origin.projected_neo_date} to {self.projected_neo_date}\n"
            # Requisition Remarks
            if self.requisition_remarks != self._origin.requisition_remarks:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Requisition Remarks: {self._origin.requisition_remarks} to {self.requisition_remarks}\n"
            # Priority
            if self.priority != self._origin.priority:
                self.update_logs += f"{user_time:%m-%d-%Y %I:%M%p} | Priority: {self._origin.priority} to {self.priority}\n"

    @api.depends('write_uid')
    def _onchange_last_update(self):
        for rec in self:
            if rec.write_uid:
                if rec.updated_by != False:
                    rec.updated_by += f"Updated By: {self.write_uid.name}\n"
                else:
                    rec.updated_by = ""

    # Requisition status validation
    # @api.constrains('x_requisition_status')
    # def _prevent_in_progress_from_closed(self):
    #     for rec in self:
    #         if self.x_requisition_status == 'in progress' and rec.x_filled == rec.x_no_of_demand:
    #             raise ValidationError(_("Can't reopen this requisition since the headcount demand is already filled"))

    # @api.constrains('x_requisition_status')
    # def _closed_status_validation(self):
    #     for rec in self:
    #         if self.x_requisition_status == 'closed' and rec.x_filled != rec.x_no_of_demand and rec.x_no_of_demand != 0:
    #             raise ValidationError(_("Headcount Demand is not yet filled"))

    # @api.constrains('x_department_id','x_job_name','x_hiring_manager')
    # def write(self, vals):
    #     group_id = self.env.ref('hr_recruitment.group_hr_recruitment_requisition_status')
    #     current_user = self.env.user
    #
    #     if group_id in current_user.groups_id:
    #         # Perform validation for the specific group
    #         if 'x_department_id' in vals:
    #             # Validate field1 value
    #             # Add your validation logic here
    #             if not self._validate_x_department_id(vals['x_department_id']):
    #                 raise ValidationError("Validation error for Client Name")
    #
    #         if 'x_job_name' in vals:
    #             # Validate field2 value
    #             # Add your validation logic here
    #             if not self._validate_x_job_name(vals['x_job_name']):
    #                 raise ValidationError("Validation error for Job Title")
    #
    #         if 'x_hiring_manager' in vals:
    #             # Validate field3 value
    #             # Add your validation logic here
    #             if not self._validate_x_job_description(vals['x_hiring_manager']):
    #                 raise ValidationError("Validation error for Job Description")
    #
    #     return super(Requisition, self).write(vals)
    #
    # def _validate_x_department_id(self, value):
    #     # Add your validation logic for field1
    #     # Return True if the value is valid, otherwise False
    #     if value == 'invalid_value':
    #         return False
    #     return True
    #
    # def _validate_x_job_name(self, value):
    #     # Add your validation logic for field2
    #     # Return True if the value is valid, otherwise False
    #     if value == 'invalid_value':
    #         return False
    #     return True
    #
    # def _validate_x_job_description(self, value):
    #     # Add your validation logic for field3
    #     # Return True if the value is valid, otherwise False
    #     if value == 'invalid_value':
    #         return False
    #     return True

    def _compute_url(self):
        # menu_id = self._context.get('menu_id', False)
        # base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        base_url = 'http://isw-hub.com/web#id=%d&cids=1&menu_id=182&action=290&model=%s&view_type=form' % (
        self.id, self._name)
        # base_url = 'http://10.2.1.26:8070/web#id=%d&cids=1&menu_id=182&action=290&model=%s&view_type=form' % (
        # self.id, self._name)
        self.x_requisition_url = base_url

    @api.depends('x_no_of_demand', 'x_filled')
    def _compute_initial_vacancy(self):
        for rec in self:
            if rec.x_no_of_demand == False:
                rec.x_remaining_vacancy = False
            else:
                rec.x_remaining_vacancy = self.x_no_of_demand
                rec.x_remaining_vacancy = self.x_no_of_demand - rec.x_filled

    # @api.depends('x_remaining_vacancy')
    # def _set_closed_status(self):
    #     # if self.x_remaining_vacancy == 0 and self.x_no_of_demand != 0:
    #     #     self.x_requisition_status = 'closed'
    #         # in setting the value of onchange use the specific value not the label
    #         # sample is: ['open'] = Open -----> the value is 'open'
    #     if self.x_no_of_demand != self.x_remaining_vacancy and self.x_filled != 0:
    #         self.x_requisition_status = 'in progress'

    @api.onchange('x_department_id')
    def onchange_x_department_id(self):
        for rec in self:
            rec.x_job_name = False

    @api.depends('x_req_sla_total')
    def _set_x_req_days_passed(self):
        for rec in self:
            if rec.x_req_sla < 31:
                self.x_days_passed = 'less_than_30_days'
            elif rec.x_req_sla > 30:
                self.x_days_passed = 'passed_30_days'

    # SLA Functionality
    @api.depends('x_date_today')
    def _compute_x_date_today(self):
        self.x_date_today = datetime.today()

    def _compute_difference(self):
        for rec in self:
            # purpose of dividing the total span of days or sla without weekends is to get the total number of weeks
            # purpose of multiplying it by 2 is to get the total number of weekends per week
            # purpose of adding 1 day is for the initial day logged the ticket (can be removed if the sla must be 0 the day ticket is logged)
            # rec.x_sla = 1 + (datetime.today() - rec.create_date).days - round(
            #     (((datetime.today() - rec.create_date).days) / 7) * 2)

            x_today = datetime.today()
            # x_today = '2022-12-07 04:04:10'
            # x_today = datetime.strptime(x_today, '%Y-%m-%d %I:%M:%S')
            x_today = pd.to_datetime(x_today.astimezone(pytz.timezone('Asia/Manila')), format="%Y-%m-%d").date()
            x_date_create = pd.to_datetime(rec.create_date.astimezone(pytz.timezone('Asia/Manila')),
                                           format="%Y-%m-%d").date()

            # x_today = pd.to_datetime(x_today.astimezone(pytz.timezone('Asia/Manila')), format="%Y-%m-%d").date()
            # x_today = pd.to_datetime("2022/12/30", format="%Y-%m-%d").date()
            # x_today = pd.to_datetime(date1 + pd.DateOffset(days=6), format="%Y-%m-%d").date()
            # x_date_create = pd.to_datetime("2022/11/28", format="%Y-%m-%d").date()
            # x_date_create = pd.to_datetime(datetime.today().astimezone(pytz.timezone('Asia/Manila')), format="%Y-%m-%d").date()
            days = np.busday_count(x_date_create, x_today)
            # IMPORTANT NOTE: Purpose of +1 day is to count the weekend if the ticket is logged over the weekend
            # since sales and client services is working also on saturday morning (they're nightshift)
            # array 0 to 6 = is days 0 is monday
            if x_date_create.weekday() == 5 or x_date_create.weekday() == 6:
                rec.x_req_sla = days + 2
            else:
                if x_today.weekday() == 5 or x_today.weekday() == 6:
                    rec.x_req_sla = days
                else:
                    rec.x_req_sla = days + 1
            
            # ONHOLD CODE

            if rec.x_requisition_status == 'on hold':

                # start date and end date has date and the onhold days has old value
                if rec.x_onhold_start_date != False and rec.x_onhold_end_date != False and rec.x_onhold_days > 0:

                    # END DATE HERE IS THE DATE REMOVED FROM BEING ON HOLD

                    var_onhold_start_date = rec.x_onhold_start_date
                    var_onhold_start_date = pd.to_datetime(
                        var_onhold_start_date.astimezone(pytz.timezone('Asia/Manila')), format="%Y-%m-%d").date()
                    var_onhold_end_date = rec.x_onhold_end_date
                    var_onhold_end_date = pd.to_datetime(var_onhold_end_date.astimezone(pytz.timezone('Asia/Manila')),
                                                         format="%Y-%m-%d").date()
                    # since end date has value the value of end date is rec.x_onhold_end_date
                    var_onhold_days = np.busday_count(var_onhold_start_date, var_onhold_end_date)

                    # rec.x_onhold_end_date = ''

                    if rec.x_old_onhold_checker == 0:
                        rec.x_old_onhold_checker = 1
                        # rec.x_req_recruitment_hiring_manager = 'new'

                        if var_onhold_start_date.weekday() == 5 or var_onhold_start_date.weekday() == 6:
                            rec.x_onhold_days = var_onhold_days + 1
                        else:
                            if var_onhold_end_date.weekday() == 5 or var_onhold_end_date.weekday() == 6:
                                rec.x_onhold_days = rec.x_onhold_days + var_onhold_days
                            else:
                                rec.x_onhold_days = (rec.x_onhold_days + var_onhold_days)
                        rec.x_onhold_counter = rec.x_onhold_counter + 1
                    else:
                        rec.x_old_onhold_checker = 2
                        # rec.x_req_recruitment_hiring_manager = 'old'

                    rec.x_req_sla = rec.x_req_sla - rec.x_onhold_days




                # start date has value and end date is null and the onhold days is 0
                else:
                    # rec.x_onhold_start_date = rec.x_date_today
                    var_onhold_start_date = rec.x_onhold_start_date
                    var_onhold_start_date = pd.to_datetime(
                        var_onhold_start_date.astimezone(pytz.timezone('Asia/Manila')), format="%Y-%m-%d").date()
                    var_onhold_end_date = datetime.today()
                    var_onhold_end_date = pd.to_datetime(var_onhold_end_date.astimezone(pytz.timezone('Asia/Manila')),
                                                         format="%Y-%m-%d").date()
                    # since end date is null the value of end date is current datetime today
                    var_onhold_days = np.busday_count(var_onhold_start_date, var_onhold_end_date)

                    if var_onhold_start_date.weekday() == 5 or var_onhold_start_date.weekday() == 6:
                        rec.x_onhold_days = var_onhold_days + 1
                    else:
                        if var_onhold_end_date.weekday() == 5 or var_onhold_end_date.weekday() == 6:
                            rec.x_onhold_days = var_onhold_days
                        else:
                            rec.x_onhold_days = var_onhold_days
                    rec.x_req_sla = rec.x_req_sla - rec.x_onhold_days
                    rec.x_old_onhold_checker = 1
                    rec.x_onhold_counter = rec.x_onhold_counter + 1

            elif rec.x_requisition_status == 'in progress' and rec.x_onhold_days > 0:
                rec.x_req_sla = rec.x_req_sla - rec.x_onhold_days
                rec.x_old_onhold_checker = 0

            elif rec.x_requisition_status == 'pending' and rec.x_onhold_days < 1 and rec.x_req_sla <= 1:
                rec.x_req_sla = 0

            elif rec.x_requisition_status == 'cancelled' or rec.x_requisition_status == 'closed':
                # rec.x_onhold_start_date = rec.x_date_today
                var_onhold_start_date = rec.x_onhold_start_date
                var_onhold_start_date = pd.to_datetime(var_onhold_start_date.astimezone(pytz.timezone('Asia/Manila')),
                                                       format="%Y-%m-%d").date()
                var_onhold_end_date = datetime.today()
                var_onhold_end_date = pd.to_datetime(var_onhold_end_date.astimezone(pytz.timezone('Asia/Manila')),
                                                     format="%Y-%m-%d").date()
                # since end date is null the value of end date is current datetime today
                var_onhold_days = np.busday_count(var_onhold_start_date, var_onhold_end_date)

                if var_onhold_start_date.weekday() == 5 or var_onhold_start_date.weekday() == 6:
                    rec.x_onhold_days = var_onhold_days + 1
                else:
                    if var_onhold_end_date.weekday() == 5 or var_onhold_end_date.weekday() == 6:
                        rec.x_onhold_days = var_onhold_days
                    else:
                        rec.x_onhold_days = var_onhold_days

                rec.x_req_sla = rec.x_req_sla - rec.x_onhold_days
                rec.x_old_onhold_checker = 0
            if rec.x_req_sla < 0:
                rec.x_req_sla = 0

            rec.x_req_sla_total = rec.x_req_sla

    def _compute_new_sla(self):
        for rec in self:
            x_today = datetime.today()
            x_today = pd.to_datetime(x_today.astimezone(pytz.timezone('Asia/Manila')), format="%Y-%m-%d").date()
            
            if rec.ongoing_sourcing_date:
                # x_today = rec.testing_datetime
                # x_today = pd.to_datetime(x_today.astimezone(pytz.timezone('Asia/Manila')), format="%Y-%m-%d").date()
                x_date_create = pd.to_datetime(rec.ongoing_sourcing_date.astimezone(pytz.timezone('Asia/Manila')),
                                           format="%Y-%m-%d").date()
                days = np.busday_count(x_date_create, x_today)
                if x_date_create.weekday() == 5 or x_date_create.weekday() == 6:
                    rec.req_ageing = days + 2
                else:
                    if x_today.weekday() == 5 or x_today.weekday() == 6:
                        rec.req_ageing = days
                    else:
                        rec.req_ageing = days + 1
            
                if rec.x_requisition_status == 'recalibrate':
                    rec.req_ageing = False
                    rec.req_ageing_total = False
                    rec.days_onhold = False
                    rec.hold_start_date = False
                    rec.hold_end_date = False
                    rec.old_onhold_checker = False
                    rec.onhold_counter = False
                    rec.ongoing_sourcing_date = False
                    rec.date_onhold = False
                    rec.end_date = False
                    rec.date_filled = False
                    rec.date_cancelled = False

                # ONHOLD CODE

                if rec.x_requisition_status == 'on hold' and rec.date_onhold:

                    # start date and end date has date and the onhold days has old value
                    if rec.date_onhold != False and rec.hold_end_date != False and rec.days_onhold > 0:
                        # END DATE HERE IS THE DATE REMOVED FROM BEING ON HOLD
                        rec.end_date = x_today 
                        var_onhold_start_date = rec.date_onhold
                        var_onhold_start_date = pd.to_datetime(var_onhold_start_date.astimezone(pytz.timezone('Asia/Manila')), format="%Y-%m-%d").date()
                        # var_onhold_end_date = rec.x_onhold_end_date
                        var_onhold_end_date = datetime.today()
                        var_onhold_end_date = pd.to_datetime(var_onhold_end_date.astimezone(pytz.timezone('Asia/Manila')),
                                                            format="%Y-%m-%d").date()
                        # since end date has value the value of end date is rec.x_onhold_end_date
                        var_onhold_days = np.busday_count(var_onhold_start_date, var_onhold_end_date)

                        # rec.x_onhold_end_date = ''

                        if rec.old_onhold_checker == 0:
                            rec.old_onhold_checker = 1
                            # rec.x_req_recruitment_hiring_manager = 'new'

                            if var_onhold_start_date.weekday() == 5 or var_onhold_start_date.weekday() == 6:
                                rec.days_onhold = var_onhold_days + 1
                            else:
                                if var_onhold_end_date.weekday() == 5 or var_onhold_end_date.weekday() == 6:
                                    rec.days_onhold = rec.days_onhold + var_onhold_days
                                else:
                                    rec.days_onhold = (rec.days_onhold + var_onhold_days)
                            rec.onhold_counter = rec.onhold_counter + 1
                        else:
                            rec.old_onhold_checker = 2
                            # rec.x_req_recruitment_hiring_manager = 'old'

                        # rec.x_req_sla = rec.x_req_sla - rec.x_onhold_days
                        # rec.x_req_sla = rec.x_req_sla

                    # start date has value and end date is null and the onhold days is 0
                    else:
                        # rec.x_onhold_start_date = rec.x_date_today
                        var_onhold_start_date = rec.date_onhold
                        var_onhold_start_date = pd.to_datetime(var_onhold_start_date.astimezone(pytz.timezone('Asia/Manila')), format="%Y-%m-%d").date()
                        # var_onhold_end_date = datetime.today()
                        var_onhold_end_date = datetime.today()
                        var_onhold_end_date = pd.to_datetime(var_onhold_end_date.astimezone(pytz.timezone('Asia/Manila')),
                                                            format="%Y-%m-%d").date()
                        # since end date is null the value of end date is current datetime today
                        var_onhold_days = np.busday_count(var_onhold_start_date, var_onhold_end_date)

                        if var_onhold_start_date.weekday() == 5 or var_onhold_start_date.weekday() == 6:
                            rec.days_onhold = var_onhold_days + 1
                        else:
                            if var_onhold_end_date.weekday() == 5 or var_onhold_end_date.weekday() == 6:
                                rec.days_onhold = var_onhold_days
                            else:
                                rec.days_onhold = var_onhold_days
                        # rec.x_req_sla = rec.x_req_sla - rec.x_onhold_days
                        rec.old_onhold_checker = 1
                        rec.onhold_counter = rec.onhold_counter + 1

                # elif rec.x_requisition_status == 'in progress' and rec.x_onhold_days > 0:
                #     rec.x_req_sla = rec.x_req_sla - rec.x_onhold_days
                #     rec.x_old_onhold_checker = 0

                elif rec.x_requisition_status == 'pending' and rec.days_onhold < 1 and rec.req_ageing <= 1:
                    rec.req_ageing = 0

                elif rec.x_requisition_status == 'cancelled' and rec.date_onhold:
                    # rec.x_onhold_start_date = rec.x_date_today
                    var_onhold_start_date = rec.date_cancelled
                    var_onhold_start_date = pd.to_datetime(var_onhold_start_date.astimezone(pytz.timezone('Asia/Manila')),
                                                        format="%Y-%m-%d").date()
                    var_onhold_end_date = datetime.today()
                    var_onhold_end_date = pd.to_datetime(var_onhold_end_date.astimezone(pytz.timezone('Asia/Manila')),
                                                        format="%Y-%m-%d").date()
                    # since end date is null the value of end date is current datetime today
                    var_onhold_days = np.busday_count(var_onhold_start_date, var_onhold_end_date)

                    if var_onhold_start_date.weekday() == 5 or var_onhold_start_date.weekday() == 6:
                        rec.days_onhold = var_onhold_days + 1
                    else:
                        if var_onhold_end_date.weekday() == 5 or var_onhold_end_date.weekday() == 6:
                            rec.days_onhold = var_onhold_days
                        else:
                            rec.days_onhold = var_onhold_days

                    rec.req_ageing = rec.req_ageing
                    rec.old_onhold_checker = 0

                elif rec.x_requisition_status == 'closed':
                    rec.days_to_fill = rec.req_ageing
                    var_onhold_start_date = rec.date_completed
                    var_onhold_start_date = pd.to_datetime(var_onhold_start_date.astimezone(pytz.timezone('Asia/Manila')),
                                                        format="%Y-%m-%d").date()
                    var_onhold_end_date = datetime.today()
                    var_onhold_end_date = pd.to_datetime(var_onhold_end_date.astimezone(pytz.timezone('Asia/Manila')),
                                                        format="%Y-%m-%d").date()
                    # since end date is null the value of end date is current datetime today
                    var_onhold_days = np.busday_count(var_onhold_start_date, var_onhold_end_date)

                    if var_onhold_start_date.weekday() == 5 or var_onhold_start_date.weekday() == 6:
                        rec.days_onhold = var_onhold_days + 1
                    else:
                        if var_onhold_end_date.weekday() == 5 or var_onhold_end_date.weekday() == 6:
                            rec.days_onhold = var_onhold_days
                        else:
                            rec.days_onhold = var_onhold_days

                    rec.req_ageing = rec.req_ageing
                    rec.old_onhold_checker = 0

                if rec.req_ageing < 0:
                    rec.req_ageing = 0

            rec.req_ageing_total = rec.req_ageing - rec.days_onhold
            rec.req_ageing = rec.req_ageing_total        

class Referral(models.Model):
    _name = "hr.referral"
    _description = "Referral"
    _order = "id desc"
    _inherit = ['mail.thread.cc', 'mail.activity.mixin', 'utm.mixin']
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char("Candidate Name", store=True, index=True)
    mobile_number = fields.Char("Candidate Mobile Number", store=True, index=True)
    email = fields.Char("Candidate Email Address", store=True, index=True)
    emp_name = fields.Char("Employee Name", store=True, index=True)
    emp_account = fields.Char("Employee Account/Program/Department", store=True, index=True)
    emp_id = fields.Char("Employee ID", store=True, index=True)
    employee_email = fields.Char('Employee Email', store=True, index=True)
    referral_ids = fields.Many2many(comodel_name='ir.attachment',
                                    relation='m2m_ir_referral_rel',
                                    column1='m2m_id',
                                    column2='attachment_id',
                                    string='Resume')
    desired_position = fields.Char("Referral's Desired Position", index=True)
    user_id = fields.Many2one('res.users', 'User')
    status = fields.Selection([('untapped', 'Untapped'), ('dispatched', 'Dispatched')], 'Status', default='untapped', store=True)
    dispatch_date = fields.Datetime('Dispatch Date')
    record_ageing = fields.Integer('Record Ageing', compute="_compute_record_ageing")
    record_ageing_ref = fields.Integer('Record Ageing Reference', store=True)
    date_today = fields.Datetime('Datetime Today', compute="_compute_date_today")
    update_logs = fields.Text('Update Logs', store=True, default="")
    requisition_id = fields.Many2one('hr.requisition', 'Requisition ID', store=True)
    received_date = fields.Char('Received Date', store=True, compute="_compute_received_date")
    dispatch_date_ref = fields.Char('Received Date', store=True)
    job_id = fields.Many2one('hr.job', 'Job Position', store=True)
    department_id = fields.Many2one('hr.department', 'Department Name', store=True)
    
    # @api.depends('status')
    # def _compute_dispatch_date_ref(self):
    #     for record in self:
    #         if record.status:
    #             date = fields.Date.from_string(record.dispatch_date).strftime('%B %d %Y')
    #             record.dispatch_date_ref = date
    #         else:
    #             record.dispatch_date_ref = False

    @api.depends('create_date')
    def _compute_received_date(self):
        for record in self:
            if record.create_date:
                date = fields.Date.from_string(record.create_date).strftime('%B %d %Y')
                record.received_date = date
            else:
                record.date = False

    # Date Today
    @api.depends('date_today')
    def _compute_date_today(self):
        self.date_today = datetime.today()

    def _compute_record_ageing(self):
        for rec in self:
            if rec.create_date and rec.date_today:
                # Calculate the age in days
                age_timedelta = rec.date_today - rec.create_date

                # Calculate the number of working days (excluding weekends)
                total_days = age_timedelta.days
                working_days = 0
                initial_date = rec.create_date

                while initial_date <= rec.date_today:
                    if initial_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        working_days += 1
                    initial_date += timedelta(days=1)

                rec.record_ageing = working_days
                rec.record_ageing_ref = rec.record_ageing
            else:
                rec.record_ageing = False        

    @api.constrains('email')
    def _referral_email_validation(self):
        is_unique_email = self.search_count([('email', '=', self.email)])
        if self.create_uid.id != 4:
            if is_unique_email > 1:
                raise ValidationError(
                    f"The email '{self.email}' is already in the system, please use a different email.")

    @api.constrains('mobile_number')
    def _mobile_validation(self):
        is_unique = self.search_count([('mobile_number', '=', self.mobile_number)])
        for rec in self:
            if self.create_uid.id != 4:
                if is_unique > 1:
                    raise ValidationError(
                        f"The mobile number '{self.mobile_number}' is already on the system, please try another.")
            if rec.mobile_number:
                if len(rec.mobile_number) != 10:
                    raise ValidationError(
                        _("The mobile number field is accepting 10 digits only. Please provide a valid mobile number."))
                return True

    # Transfer to all applicants function
    def transfer_records_applicants(self):
        for record in self:
            if not record.requisition_id:
                raise ValidationError(
                    f"'{self.name}' | Please input a Requisition ID before transferring the referral.")

            record.sudo().write({'status': 'dispatched'})
            record.write({'dispatch_date': record.date_today})

            # set timezone
            user_timezone = 'Asia/Singapore'
            utc_now = datetime.utcnow()
            # convert time
            user_timezone = pytz.timezone(user_timezone)
            user_time = utc_now.astimezone(user_timezone)

            if not self.update_logs:
                self.update_logs = ""
            self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Status: {self.status}\n\n"

            # Create a list to store attachment IDs for the transferred records
            attachment_ids = []

            for attachment in record.referral_ids:
                new_attachment = attachment.copy()
                attachment_ids.append(new_attachment.id)

            # Create a new hr.applicant record with the attachments transferred to the new referral_ids field
            new_applicant = self.env['hr.applicant'].create({
                'partner_name': record.name,
                'x_mobile_number': record.mobile_number,
                'email_from': record.email,
                'employee_email': record.employee_email,
                'employee_id': record.emp_id,
                'employee_account': record.emp_account,
                'x_app_source_category': 'employee referral',
                'referral_position': record.desired_position,
                'x_referrer_name': record.emp_name,
                'x_requisition_id': record.requisition_id.id,
                'referral_ids': [(6, 0, attachment_ids)]  # Set the copied attachments to the new referral_ids field
            })
        return True

    # Update Logs
    @api.onchange('name', 'email', 'mobile_number', 'referral_ids', 'desired_position', 'emp_id', 'emp_name', 'emp_account', 'status', 'requisition_id', 'stage_id')
    def _onchange_update_logs(self):
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
            # Candidate Name
            if self.name != self._origin.name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Candidate Name: {self._origin.name} to {self.name}\n\n"
            # Candidate Email Address
            if self.email != self._origin.email:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Candidate Email Address: {self._origin.email} to {self.email}\n\n"
            # Candidate Mobile Number
            if self.mobile_number != self._origin.mobile_number:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Candidate Mobile Number: {self._origin.mobile_number} to {self.mobile_number}\n\n"
            # Referral's Desired Position
            if self.desired_position != self._origin.desired_position:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Referral's Desired Position: {self._origin.desired_position} to {self.desired_position}\n\n"
            # Employee ID
            if self.emp_id != self._origin.emp_id:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Employee ID: {self._origin.emp_id} to {self.emp_id}\n\n"
            # Employee Name
            if self.emp_name != self._origin.emp_name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Employee Name: {self._origin.emp_name} to {self.emp_name}\n\n"
            # Employee Account/Program/Department
            if self.emp_account != self._origin.emp_account:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Employee Account/Program/Department: {self._origin.emp_account} to {self.emp_account}\n\n"
            # Status
            if self.status != self._origin.status:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Status: {self._origin.status} to {self.status}\n\n"
            # Requisition ID
            if self.requisition_id.x_req_id != self._origin.requisition_id.x_req_id:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Requisition ID: {self._origin.requisition_id.x_req_id} to {self.requisition_id.x_req_id}\n\n"

class JobApplication(models.Model):
    _name = "hr.form"
    _description = "Job Application"
    _order = "id desc"
    _inherit = ['mail.thread.cc', 'mail.activity.mixin', 'utm.mixin']
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Applicant Name', store=True)
    email = fields.Char('Email', store=True)
    mobile_number = fields.Char('Mobile Number', store=True)
    attachment_id = fields.Many2many(comodel_name='ir.attachment',
                                    relation='m2m_ir_form_rel',
                                    column1='m2m_id',
                                    column2='attachment_id',
                                    string='CV')
    linkedin = fields.Char("LinkedIn Profile", store=True)
    requisition_id = fields.Many2one('hr.requisition', "Requisition ID", store=True)
    status = fields.Selection([('untapped','Untapped'),('dispatched','Dispatched')], "Status", default='untapped', store=True)
    dispatch_date = fields.Datetime("Dispatch Date")
    record_ageing = fields.Integer('Record Ageing', compute="_compute_record_ageing")
    record_ageing_ref = fields.Integer('Record Ageing Reference', store=True)
    date_today = fields.Datetime("Datetime Today", compute="_compute_date_today")
    update_logs = fields.Text("Fields Update Logs", store=True)
    user_id = fields.Many2one('res.users', 'User')

    # Date Today
    @api.depends('date_today')
    def _compute_date_today(self):
        self.date_today = datetime.today()

    def _compute_record_ageing(self):
        for rec in self:
            if rec.create_date and rec.date_today:
                # Calculate the age in days
                age_timedelta = rec.date_today - rec.create_date

                # Calculate the number of working days (excluding weekends)
                total_days = age_timedelta.days
                working_days = 0
                initial_date = rec.create_date

                while initial_date <= rec.date_today:
                    if initial_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        working_days += 1
                    initial_date += timedelta(days=1)

                rec.record_ageing = working_days
                rec.record_ageing_ref = rec.record_ageing
            else:
                rec.record_ageing = False        

    # Transfer to all applicants function
    def transfer_records_applicants(self):
        for record in self:
            if not record.requisition_id:
                raise ValidationError(
                    f"'{self.name}' | Please input a Requisition ID before transferring the referral.")

            record.sudo().write({'status': 'dispatched'})
            record.write({'dispatch_date': record.date_today})

            # set timezone
            user_timezone = 'Asia/Singapore'
            utc_now = datetime.utcnow()
            # convert time
            user_timezone = pytz.timezone(user_timezone)
            user_time = utc_now.astimezone(user_timezone)

            if not self.update_logs:
                self.update_logs = ""
            self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Status: {self.status}\n\n"

            # Create a list to store attachment IDs for the transferred records
            attachment_ids = []

            for attachment in record.attachment_id:
                new_attachment = attachment.copy()
                attachment_ids.append(new_attachment.id)

            # Create a new hr.applicant record with the attachments transferred to the new referral_ids field
            new_applicant = self.env['hr.applicant'].create({
                'partner_name': record.name,
                'x_mobile_number': record.mobile_number,
                'email_from': record.email,
                'x_app_source_category': 'online-digital',
                'x_app_specific_source_last': 2,
                'linkedin_profile': record.linkedin,
                'x_requisition_id': record.requisition_id.id,
                'referral_ids': [(6, 0, attachment_ids)]  # Set the copied attachments to the new referral_ids field
            })
        return True

class Sourcing(models.Model):
    _name = "hr.sourcing"
    _description = "Sourcing"
    _order = "id desc"
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Sourcing Name', store=True)
    user_id = fields.Many2one('res.users', 'User', store=True)
    id_reference = fields.Integer('Id Reference', related="user_id.id", store=True)

class JobPortal(models.Model):
    _name = "hr.portal"
    _description = "Job Portal"
    _order = "priority desc, id desc"
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Applicant Name', store=True)
    email = fields.Char('Email', store=True)
    priority = fields.Char('Priority', store=True)
    mobile_number = fields.Char('Mobile Number', store=True)
    attachment_id = fields.Many2many(comodel_name='ir.attachment',
                                     relation='m2m_ir_portal_rel',
                                     column1='m2m_id',
                                     column2='attachment_id',
                                     string='CV')
    linkedin = fields.Char("LinkedIn Profile", store=True)
    requisition_id = fields.Many2one('hr.requisition', "Requisition ID", store=True)
    status = fields.Selection([('untapped', 'Untapped'), ('dispatched', 'Dispatched')], "Status", default='untapped',
                              store=True)
    dispatch_date = fields.Datetime("Dispatch Date")
    # record_ageing = fields.Integer('Record Ageing')
    record_ageing = fields.Integer('Record Ageing', compute="_compute_record_ageing")
    record_ageing_ref = fields.Integer('Record Ageing Reference', store=True)
    # date_today = fields.Datetime("Datetime Today")
    date_today = fields.Datetime("Datetime Today", compute="_compute_date_today")
    remarks = fields.Text('Remarks', store=True)
    update_logs = fields.Text("Fields Update Logs", store=True)
    user_id = fields.Many2one('res.users', 'User')
    specific_source = fields.Many2one('hr.specificsource', string='Specific Source',
                                      domain="[('x_app_source_category', '=', 'online-digital')]", store=True)
    app_source_category = fields.Selection(
        [('online-digital', 'Online-Digital'), ('proactive_search', 'Pro-active Search'),
         ('recruitment-marketing', 'Recruitment-Marketing'), ('employee referral', 'Employee Referral'),
         ('rehire', 'Rehire'), ('open house', 'Open House')],
        'Channel', store=True, default='online-digital')
    received_date = fields.Date('Received Date', store=True)    

    # Date Today
    @api.depends('date_today')
    def _compute_date_today(self):
        self.date_today = datetime.today()

    def _compute_record_ageing(self):
        for rec in self:
            if rec.create_date and rec.date_today:
                # Calculate the age in days
                age_timedelta = rec.date_today - rec.create_date

                # Calculate the number of working days (excluding weekends)
                total_days = age_timedelta.days
                working_days = 0
                initial_date = rec.create_date

                while initial_date <= rec.date_today:
                    if initial_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        working_days += 1
                    initial_date += timedelta(days=1)

                rec.record_ageing = working_days
                rec.record_ageing_ref = rec.record_ageing
            else:
                rec.record_ageing = False

    # Transfer to all applicants function
    def transfer_records_applicants_portal(self):
        for record in self:
            if not record.requisition_id:
                raise ValidationError(
                    f"'{self.name}' | Please input a Requisition ID before transferring the referral.")

            record.sudo().write({'status': 'dispatched'})
            record.write({'dispatch_date': record.date_today})

            # set timezone
            user_timezone = 'Asia/Singapore'
            utc_now = datetime.utcnow()
            # convert time
            user_timezone = pytz.timezone(user_timezone)
            user_time = utc_now.astimezone(user_timezone)

            if not self.update_logs:
                self.update_logs = ""
            self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Status: {self.status}\n\n"

            # Create a list to store attachment IDs for the transferred records
            attachment_ids = []

            for attachment in record.attachment_id:
                new_attachment = attachment.copy()
                attachment_ids.append(new_attachment.id)

            # Create a new hr.applicant record with the attachments transferred to the new referral_ids field
            new_applicant = self.env['hr.applicant'].create({
                'partner_name': record.name,
                'x_mobile_number': record.mobile_number,
                'email_from': record.email,
                'x_app_source_category': 'online-digital',
                'x_app_specific_source_last': record.specific_source.id,
                'linkedin_profile': record.linkedin,
                'x_requisition_id': record.requisition_id.id,
                'referral_ids': [(6, 0, attachment_ids)]  # Set the copied attachments to the new referral_ids field
            })
        return True

    @api.constrains('email')
    def _email_validation(self):
        is_unique_email_portal = self.search_count([('email', '=', self.email)])
        is_unique_email = self.env['hr.applicant'].search_count([('email_from', '=', self.email)])
        print(is_unique_email)
        is_unique_email_duplicate = self.env['hr.applicant'].search_count(
            [('email_from', '=', self.email), ('record_ageing_ref', '<', 90)])
        if self.email != False:
            if is_unique_email > 1:
                raise ValidationError(
                    f"The provided email '{self.email}' was already used in an existing application. To avoid duplicate records, please provide a non-existent email.")
            if is_unique_email_duplicate:
                raise ValidationError(
                    f"The provided email '{self.email}' was already used in an existing application with record ageing of '{self.record_ageing_ref}'. To avoid duplicate records, please provide a non-existent email or wait till the existing application turns 90 days.")
            if is_unique_email_portal > 1:
                raise ValidationError(
                    f"The provided email '{self.email}' was already used in an existing application. To avoid duplicate records, please provide a non-existent email.")

    @api.constrains('mobile_number')
    def _mobile_validation(self):
        is_unique_mobile = self.search_count([('mobile_number', '=', self.mobile_number)])
        is_unique = self.env['hr.applicant'].search_count([('x_mobile_number', '=', self.mobile_number)])
        print(is_unique)
        if is_unique == 1:
            raise ValidationError(
                f"The provided primary mobile number '{self.mobile_number}' was already used in an existing application. To avoid duplicate records, please provide a non-existent mobile number.")
        for rec in self:
            if rec.mobile_number:
                if len(rec.mobile_number) != 10:
                    raise ValidationError(_(f"'{self.mobile_number}' is not a valid mobile number."))
                return True
            if is_unique_mobile > 1:
                raise ValidationError(
                f"The provided primary mobile number '{self.mobile_number}' was already used in an existing application. To avoid duplicate records, please provide a non-existent mobile number.")
    
    # Update Logs
    @api.onchange('name', 'email', 'mobile_number', 'attachment_id', 'requisition_id', 'specific_source')
    def _onchange_update_logs(self):
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
            # Candidate Name
            if self.name != self._origin.name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Candidate Name: {self._origin.name} to {self.name}\n\n"
            # Candidate Email Address
            if self.email != self._origin.email:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Candidate Email Address: {self._origin.email} to {self.email}\n\n"
            # Candidate Mobile Number
            if self.mobile_number != self._origin.mobile_number:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Candidate Mobile Number: {self._origin.mobile_number} to {self.mobile_number}\n\n"
            # Requisition ID
            if self.requisition_id.x_req_id != self._origin.requisition_id.x_req_id:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Requisition ID: {self._origin.requisition_id.x_req_id} to {self.requisition_id.x_req_id}\n\n"
            # Specific Source
            if self.specific_source.x_app_specific_source_new != self._origin.specific_source.x_app_specific_source_new:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Specific Source: {self._origin.specific_source.x_app_specific_source_new} to {self.specific_source.x_app_specific_source_new}\n\n"    



class Pooling(models.Model):
    _name = "hr.pooling"
    _description = "For Pooling"
    _order = "priority desc, id desc"
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Applicant Name', store=True)
    email = fields.Char('Email', store=True)
    priority = fields.Char('Priority', store=True)
    mobile_number = fields.Char('Mobile Number', store=True)
    attachment_id = fields.Many2many(comodel_name='ir.attachment',
                                     relation='m2m_ir_pooling_rel',
                                     column1='m2m_id',
                                     column2='attachment_id',
                                     string='CV')
    linkedin = fields.Char("LinkedIn Profile", store=True)
    requisition_id = fields.Many2one('hr.requisition', "Requisition ID", store=True)
    dept_name = fields.Char(string='Client Name', related='requisition_id.x_department_id.name')
    job_title_name = fields.Char(string='Job Title', readonly=True, related='requisition_id.x_job_name.name')
    status = fields.Selection([('untapped', 'Untapped'), ('dispatched_applicants', 'Dispatched to All Applicants'), 
                               ('dispatched_portal', 'Dispatched to Job Portal')], "Status", default='untapped', store=True)
    dispatch_date = fields.Datetime("Dispatch Date")
    # record_ageing = fields.Integer('Record Ageing')
    record_ageing = fields.Integer('Record Ageing', compute="_compute_record_ageing")
    record_ageing_ref = fields.Integer('Record Ageing Reference', store=True)
    # date_today = fields.Datetime("Datetime Today")
    date_today = fields.Datetime("Datetime Today", compute="_compute_date_today")
    remarks = fields.Text('Remarks', store=True)
    update_logs = fields.Text("Fields Update Logs", store=True)
    user_id = fields.Many2one('res.users', 'User')
    specific_source = fields.Many2one('hr.specificsource', string='Specific Source', store=True)
    x_app_source_category = fields.Selection(
        [('online-digital', 'Online-Digital'), ('proactive_search', 'Pro-active Search'),
         ('recruitment-marketing', 'Recruitment-Marketing'), ('employee referral', 'Employee Referral'),
         ('rehire', 'Rehire'), ('open house', 'Open House')],
        'Channel', store=True, default='online-digital')
    received_date = fields.Date('Received Date', store=True)
    x_app_specific_source_category = fields.Char("Admin Field", store=True)
    profile_link = fields.Char('Profile Link', store=True)

    # Date Today
    @api.depends('date_today')
    def _compute_date_today(self):
        self.date_today = datetime.today()

    def _compute_record_ageing(self):
        for rec in self:
            if rec.create_date and rec.date_today:
                # Calculate the age in days
                age_timedelta = rec.date_today - rec.create_date

                # Calculate the number of working days (excluding weekends)
                total_days = age_timedelta.days
                working_days = 0
                initial_date = rec.create_date

                while initial_date <= rec.date_today:
                    if initial_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        working_days += 1
                    initial_date += timedelta(days=1)

                rec.record_ageing = working_days
                rec.record_ageing_ref = rec.record_ageing
            else:
                rec.record_ageing = False

    # Transfer to all applicants function
    def transfer_records_applicants_portal(self):
        for record in self:
            if not record.requisition_id:
                raise ValidationError(
                    f"'{self.name}' | Please input a Requisition ID before transferring the referral.")

            record.sudo().write({'status': 'dispatched_applicants'})
            record.write({'dispatch_date': record.date_today})

            # set timezone
            user_timezone = 'Asia/Singapore'
            utc_now = datetime.utcnow()
            # convert time
            user_timezone = pytz.timezone(user_timezone)
            user_time = utc_now.astimezone(user_timezone)

            if not self.update_logs:
                self.update_logs = ""
            self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Status: Dispatched to All Applicants\n\n"

            # Create a list to store attachment IDs for the transferred records
            attachment_ids = []

            for attachment in record.attachment_id:
                new_attachment = attachment.copy()
                attachment_ids.append(new_attachment.id)

            # Create a new hr.applicant record with the attachments transferred to the new referral_ids field
            new_applicant = self.env['hr.applicant'].create({
                'partner_name': record.name,
                'x_mobile_number': record.mobile_number,
                'email_from': record.email,
                'x_app_source_category': record.x_app_source_category,
                'x_app_specific_source_last': record.specific_source.id,
                'linkedin_profile': record.linkedin,
                'x_requisition_id': record.requisition_id.id,
                'profile_link': record.profile_link,
                'referral_ids': [(6, 0, attachment_ids)]  # Set the copied attachments to the new referral_ids field
            })
        return True
    
    # Transfer to job portal
    # def transfer_records_job_portal(self):
    #     for record in self:
    #         if not record.requisition_id:
    #             raise ValidationError(
    #                 f"'{self.name}' | Please input a Requisition ID before transferring the referral.")
            
    #         if record.x_app_source_category != 'online-digital':
    #             raise ValidationError(
    #                 f"'{self.name}' | Please set the Channel to Online-Digital before transferring to Job Portal.")

    #         record.sudo().write({'status': 'dispatched_portal'})
    #         record.write({'dispatch_date': record.date_today})

    #         # set timezone
    #         user_timezone = 'Asia/Singapore'
    #         utc_now = datetime.utcnow()
    #         # convert time
    #         user_timezone = pytz.timezone(user_timezone)
    #         user_time = utc_now.astimezone(user_timezone)

    #         if not self.update_logs:
    #             self.update_logs = ""
    #         self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Status: Dispatched to Job Portal\n\n"

    #         # Create a list to store attachment IDs for the transferred records
    #         attachment_ids = []

    #         for attachment in record.attachment_id:
    #             new_attachment = attachment.copy()
    #             attachment_ids.append(new_attachment.id)

    #         # Create a new hr.portal record with the attachments transferred to the new referral_ids field
    #         new_applicant = self.env['hr.portal'].create({
    #             'name': record.name,
    #             'mobile_number': record.mobile_number,
    #             'email': record.email,
    #             'app_source_category': record.x_app_source_category,
    #             'specific_source': record.specific_source.id,
    #             'requisition_id': record.requisition_id.id,
    #             'attachment_id': [(6, 0, attachment_ids)]  # Set the copied attachments to the new attachment_ids field
    #         })
    #     return True

    @api.constrains('email')
    def _email_validation(self):
        is_unique_email_pooling = self.search_count([('email', '=', self.email)])
        is_unique_email = self.env['hr.applicant'].search_count([('email_from', '=', self.email)])
        print(is_unique_email)
        is_unique_email_duplicate = self.env['hr.applicant'].search_count(
            [('email_from', '=', self.email), ('record_ageing_ref', '<', 90)])
        if self.email != False:
            if is_unique_email > 1:
                raise ValidationError(
                    f"The provided email '{self.email}' was already used in an existing application. To avoid duplicate records, please provide a non-existent email.")
            if is_unique_email_duplicate:
                raise ValidationError(
                    f"The provided email '{self.email}' was already used in an existing application with record ageing of '{self.record_ageing_ref}'. To avoid duplicate records, please provide a non-existent email or wait till the existing application turns 90 days.")
            if is_unique_email_pooling > 1:
                raise ValidationError(
                    f"The provided email '{self.email}' was already used in an existing application. To avoid duplicate records, please provide a non-existent email.")

    @api.constrains('mobile_number')
    def _mobile_validation(self):
        is_unique_mobile = self.search_count([('mobile_number', '=', self.mobile_number)])
        is_unique = self.env['hr.applicant'].search_count([('x_mobile_number', '=', self.mobile_number)])
        print(is_unique)
        if is_unique == 1:
            raise ValidationError(
                f"The provided primary mobile number '{self.mobile_number}' was already used in an existing application. To avoid duplicate records, please provide a non-existent mobile number.")
        for rec in self:
            if rec.mobile_number:
                if len(rec.mobile_number) != 10:
                    raise ValidationError(_(f"'{self.mobile_number}' is not a valid mobile number."))
                return True
            if is_unique_mobile > 1:
                raise ValidationError(
                f"The provided primary mobile number '{self.mobile_number}' was already used in an existing application. To avoid duplicate records, please provide a non-existent mobile number.")
            
    # Update Logs
    @api.onchange('name', 'email', 'mobile_number', 'attachment_id', 'requisition_id', 'specific_source', 'x_app_source_category')
    def _onchange_update_logs(self):
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
            # Candidate Name
            if self.name != self._origin.name:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Candidate Name: {self._origin.name} to {self.name}\n\n"
            # Candidate Email Address
            if self.email != self._origin.email:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Candidate Email Address: {self._origin.email} to {self.email}\n\n"
            # Candidate Mobile Number
            if self.mobile_number != self._origin.mobile_number:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Candidate Mobile Number: {self._origin.mobile_number} to {self.mobile_number}\n\n"
            # Requisition ID
            if self.requisition_id.x_req_id != self._origin.requisition_id.x_req_id:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Requisition ID: {self._origin.requisition_id.x_req_id} to {self.requisition_id.x_req_id}\n\n"
            # Specific Source
            if self.specific_source.x_app_specific_source_new != self._origin.specific_source.x_app_specific_source_new:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Specific Source: {self._origin.specific_source.x_app_specific_source_new} to {self.specific_source.x_app_specific_source_new}\n\n"      
            # Channel
            if self.x_app_source_category != self._origin.x_app_source_category:
                self.update_logs += f"{self.env.user.name}\n{user_time:%m/%d/%Y %I:%M%p} | Channel: {self._origin.x_app_source_category} to {self.x_app_source_category}\n\n"      
            
class PoolingStages(models.Model):
    _name = "hr.pooling_stages"
    _description = "Pooling Stages"
    _order = "priority desc, id desc"
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Stage Name', store=True)
    priority = fields.Char('Priority', store=True)
    
class StageLogs(models.Model):
    _name = "hr.stagelogs"
    _description = "Applicant Stage Logs"
    _order = "priority desc, id desc"
    _rec_name = "id"

    active = fields.Boolean("Active", default=True, help="If the active field is set to false, it will allow you to hide the case without removing it.")
    record_id = fields.Many2one('hr.applicant', string="Record", store=True)
    priority = fields.Char('Priority', store=True)
    # Old Data                                        
    ov_datetime = fields.Datetime('Initial Date', store=True)
    ov_stage = fields.Char('Old Stage', store=True)
    # New Data
    nv_datetime = fields.Datetime('Changed Date', store=True)
    nv_stage = fields.Char('New Stage', store=True)
    # Final Days
    days_duration = fields.Integer('Days Duration', compute="_compute_days_duration", store=True)
    
    @api.depends('ov_datetime', 'nv_datetime')
    def _compute_days_duration(self):
        for record in self:
            if record.ov_datetime and record.nv_datetime:
                initial_date = record.ov_datetime
                changed_date = record.nv_datetime
                duration = 1  # Initialize duration to include the initial date
                current_date = initial_date + timedelta(days=1)  # Start from the day after the initial date
                while current_date <= changed_date:
                    if current_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        duration += 1
                    current_date += timedelta(days=1)
                record.days_duration = duration
            else:
                record.days_duration = 0
    
class Recruiter(models.Model):
    _name = "hr.recruiter"
    _description = "Recruiter"
    _rec_name = "name"

    active = fields.Boolean("Active", default=True, help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Recruiter', store=True)
    
class Blacklist(models.Model):
    _name = "hr.blacklist"
    _description = "Blacklist"
    _order = "id desc"
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Blacklist Name', store=True)                
    email = fields.Char('Email', store=True)
    testField = fields.Char('Test Field', store=True)
       
class CandidateForm(models.Model):
    _name = "hr.candidate"
    _description = "Candidate Form"
    _order = "id desc"
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Candidate Name', store=True)                
    email = fields.Char('Candidate Email', store=True)
    residing_metro_manila = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Are you currently residing within Metro Manila?', store=True)
    relocate = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='If not residing in Metro Manila, are you willing to relocate to Metro Manila for this position?', store=True)
    specification_ids = fields.Many2many('hr.specification', string='Do you have any specific or obligatory appointments in the next twelve (12) months? Please check all that apply:', store=True)
    appointments_specification = fields.Text('If you ticked any of the first five items, please specify details:', store=True)
    diagnosed = fields.Text('Have you been previously diagnosed with or treated for any medical condition, which, if left untreated, may adversely affect your ability to perform the duties and responsibilities attendant to the position for which you are applying? If so, please specify.', store=True)
    medical_condition = fields.Text('Do you presently have any medical condition, physical injury, impairment, or disability that may in any manner adversely affect your ability to adequately and satisfactorily perform the duties and responsibilities attendant to the position for which you are applying? If so, please specify.', store=True)
    combined = fields.Boolean('Combined', store=True)
    
    def combine_candidate_survey(self):
        for record in self:
            record.write({'combined': True})
            
            existing_applicant = self.env['hr.applicant'].search([('email_from', '=', record.email)], limit=1)
            # Create a new hr.applicant record with the attachments transferred to the new referral_ids field
            if existing_applicant:
                existing_applicant.write({
                    'residing_metro_manila': record.residing_metro_manila,
                    'relocate': record.relocate,
                    'email_from': record.email,
                    'specification_ids': record.specification_ids,
                    'appointments_specification': record.appointments_specification,
                    'diagnosed': record.diagnosed,
                    'medical_condition': record.medical_condition,
                })
            else:
                raise ValidationError('There is no existing application record with the provided applicant email(s). "' + record.email + '"')

        return True
    
class AppointmentsSpecification(models.Model):
    _name = "hr.specification"
    _description = "Appointments Specification"
    _order = "id ASC"
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Name', store=True)    
    sequence = fields.Integer('Sequence', store=True)

class HRApplicant(models.Model):
    _inherit = 'hr.applicant'
    
    def action_view_candidate(self):
        self.ensure_one()
        email = self.email_from  # assuming 'email_from' is the field name for email
        action = self.env.ref('hr_recruitment.action_candidate_by_email')
        action = action.read()[0]
        # action['domain'] = [('email', '=', email)]
        action['context'] = {'search_default_email': email, 'default_applicant_id': self.id}
        return action
    
class RecruitmentManager(models.Model):
    _name = "hr.recruitmentmanager"
    _description = "Recruitment Manager"
    _order = "id ASC"
    _rec_name = "name"

    active = fields.Boolean("Active", default=True,
                            help="If the active field is set to false, it will allow you to hide the case without removing it.")
    name = fields.Char('Name', store=True)    
    sequence = fields.Integer('Sequence', store=True)
