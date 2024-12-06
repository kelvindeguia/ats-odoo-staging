from odoo import http
from odoo.http import request
from odoo.http import Response
import base64

class WebsiteFormController(http.Controller):
    @http.route('/referral/', type='http', auth="public", website=True)
    def website_form(self, **post):
        # Render the form template again
        return http.request.render('hr_recruitment.test_form_2')

    @http.route('/referral/website_thanks/', type='http', auth='public', website=True)
    def referral_website_thanks(self, **post):
        # Extract data from the form submission
        emp_name = post.get('emp_name')
        employee_email = post.get('employee_email')
        emp_id = post.get('emp_id')
        emp_account = post.get('emp_account')
        name = post.get('name')
        email = post.get('email')
        mobile_number = post.get('mobile_number')
        desired_position = post.get('desired_position')
        job_id = post.get('job_id')
        department_id = post.get('department_id')
        
        # Retrieve the job data from the session
        job_id_from_session = request.session.get('job_id')
        department_id_from_session = request.session.get('department_id')
        job_name_from_session = request.session.get('job_name')
        
        if job_id_from_session:
            # Fetch the job object (optional, if you need it to fetch other details)
            job = request.env['hr.job'].sudo().browse(job_id_from_session)
            
        if job_name_from_session:
            # Fetch the job object (optional, if you need it to fetch other details)
            job_name = request.env['hr.job'].sudo().browse(job_name_from_session)
            
        if department_id_from_session:
            # Fetch the job object (optional, if you need it to fetch other details)
            department = request.env['hr.job'].sudo().browse(department_id_from_session)
        
        # Check for existing records
        existing_referrals = http.request.env['hr.referral'].sudo().search([
            '|',
            ('email', '=', email),
            ('mobile_number', '=', mobile_number),
            # ('record_ageing_ref', '<', 90)
        ])

        existing_referrals_applicant = http.request.env['hr.applicant'].sudo().search([
            '|',
            ('email_from', '=', email),
            ('x_mobile_number', '=', mobile_number),
            # ('record_ageing_ref', '<', 90)
        ])

        blacklisted_applicant = http.request.env['hr.blacklist'].sudo().search([
            ('email', '=', email),
            # ('record_ageing_ref', '<', 90)
        ])

        if existing_referrals or existing_referrals_applicant or blacklisted_applicant:
            error_message = "Duplicate entry found. Please ensure your data is unique."
            return http.request.render("hr_recruitment.duplicate_entry", {'error_message': error_message})

        # Handle the uploaded resume
        resume = http.request.httprequest.files.get('resume')
        resume_data = None
        if resume:
            resume_name = resume.filename
            resume_data = resume.read()

        # Find the user by name
        user_name = "Referral"
        user = http.request.env['res.users'].sudo().search([('name', '=', user_name)], limit=1)

        # Create a new hr.referral record with the extracted data
        referral_data = {
            'emp_name': emp_name,
            'employee_email': employee_email,
            'emp_id': emp_id,
            'emp_account': emp_account,
            'name': name,
            'email': email,
            'mobile_number': mobile_number,
            'desired_position': desired_position,
            'referral_ids': [(0, 0, {
                'name': resume_name,
                'res_model': 'hr.referral',
                'res_id': 0,
                'type': 'binary',
                'datas': base64.b64encode(resume_data),
                'mimetype': 'application/pdf',
            })] if resume_data else [],
            'user_id': user.id if user else False,
        }

        referral = http.request.env['hr.referral'].sudo().create(referral_data)

        # Continue with any additional actions or responses
        # For example, you can display a thank-you message
        return http.request.render("hr_recruitment.referral_thanks", {})

# OLD REFERRAL CONTROLLER BACKUP
# class WebsiteFormController(http.Controller):
#     @http.route('/referral/', type='http', auth="public", website=True)
#     def website_form(self, **post):
#         # Render the form template again
#         return request.render('hr_recruitment.test_form_2')
#     @http.route('/referral/website_thanks/', type='http', auth='public', website=True)
#     def referral_website_thanks(self, **post):
#         # Extract data from the form submission
#         emp_name = post.get('emp_name')
#         employee_email = post.get('employee_email')
#         emp_id = post.get('emp_id')
#         emp_account = post.get('emp_account')
#         name = post.get('name')
#         email = post.get('email')
#         mobile_number = post.get('mobile_number')
#         desired_position = post.get('desired_position')
#         existing_email = request.env['hr.referral'].sudo().search_count([('record_ageing_ref', '<', 90), ('email', '=', email)])
#         existing_applicant_email = request.env['hr.applicant'].sudo().search_count([('record_ageing_ref', '<', 90), ('email_from', '=', email)])
#         existing_mobile = request.env['hr.referral'].sudo().search_count([('record_ageing_ref', '<', 90),('mobile_number', '=', mobile_number)])
#         existing_applicant_mobile = request.env['hr.applicant'].sudo().search_count([('record_ageing_ref', '<', 90),('x_mobile_number', '=', mobile_number)])
#         existing_form_email = request.env['hr.form'].sudo().search_count([('record_ageing_ref', '<', 90), ('email', '=', email)])
#         existing_form_mobile = request.env['hr.form'].sudo().search_count([('record_ageing_ref', '<', 90),('mobile_number', '=', mobile_number)])
        
#         if existing_email or existing_applicant_email or existing_form_email:
#             error_response = Response("The referral's email was already on the system, please try another.", status=400,
#                                       content_type='application/json')
#             return error_response
#         if existing_mobile or existing_applicant_mobile or existing_form_mobile:
#             error_response = Response("The referral's mobile number was already on the system, please try another.",
#                                       status=401,
#                                       content_type='application/json')
#             return error_response
#         if emp_name == 'N/A' or emp_name == 'n/a' or emp_name == 'N/A' or emp_name == 'n/a':
#             error_response = Response("N/A or n/a is not applicable, please try another.",
#                                       status=401,
#                                       content_type='application/json')
#             return error_response
#         if len(mobile_number) != 10:
#             error_response = Response(
#                 "The mobile number field is accepting 10 digits only. Please provide a valid mobile number.",
#                 status=401,
#                 content_type='application/json')
#             return error_response
#         # Handle the uploaded resume
#         resume = request.httprequest.files.get('resume')
#         resume_data = None
#         if resume:
#             resume_name = resume.filename
#             resume_data = resume.read()

#         # Find the user by name
#         user_name = "Referral"
#         user = request.env['res.users'].sudo().search([('name', '=', user_name)], limit=1)

#         # Create a new hr.referral record with the extracted data
#         referral_data = {
#             'emp_name': emp_name,
#             'employee_email': employee_email,
#             'emp_id': emp_id,
#             'emp_account': emp_account,
#             'name': name,
#             'email': email,
#             'mobile_number': mobile_number,
#             'desired_position': desired_position,
#             'referral_ids': [(0, 0, {
#                 'name': resume_name,
#                 'res_model': 'hr.referral',
#                 'res_id': 0,
#                 'type': 'binary',
#                 'datas': resume_data,
#                 'mimetype': 'application/pdf',
#                 'datas': base64.b64encode(resume_data),
#             })] if resume_data else [],
#             'user_id': user.id if user else False,
#         }

#         referral = request.env['hr.referral'].sudo().create(referral_data)

#         # Continue with any additional actions or responses
#         # For example, you can display a thank-you message
#         return request.render("hr_recruitment.referral_thanks", {})
    
class JobFormController(http.Controller):
    @http.route('/jobs/apply', type='http', auth="public", website=True)
    def website_form(self, **post):
        # Render the form template again
        return request.render('hr_recruitment.job_form_template')

    @http.route('/jobs/apply/job_thanks/', type='http', auth='public', website=True)
    def application_thanks(self, **post):
        # Extract data from the form submission
        name = post.get('name')
        email = post.get('email')
        mobile_number = post.get('mobile_number')
        linkedin = post.get('linkedin')
        existing_email = request.env['hr.form'].sudo().search([('email', '=', email)], limit=1)
        existing_applicant_email = request.env['hr.applicant'].sudo().search([('email_from', '=', email)], limit=1)
        existing_mobile = request.env['hr.form'].sudo().search([('mobile_number', '=', mobile_number)], limit=1)
        existing_applicant_mobile = request.env['hr.applicant'].sudo().search([('x_mobile_number', '=', mobile_number)],
                                                                              limit=1)
        existing_form_email = request.env['hr.form'].sudo().search([('email', '=', email)], limit=1)
        existing_form_mobile = request.env['hr.form'].sudo().search([('mobile_number', '=', mobile_number)],
                                                                              limit=1)

        if existing_email or existing_applicant_email or existing_form_email:
            error_response = Response("The applicant's email was already on the system, please try another.", status=400,
                                      content_type='application/json')
            return error_response
        if existing_mobile or existing_applicant_mobile or existing_form_mobile:
            error_response = Response("The applicant's mobile number was already on the system, please try another.",
                                      status=401,
                                      content_type='application/json')
            return error_response
        if name == 'N/A' or name == 'n/a' or name == 'N/A' or name == 'n/a':
            error_response = Response("N/A or n/a is not applicable, please try another.",
                                      status=401,
                                      content_type='application/json')
            return error_response
        if len(mobile_number) != 10:
            error_response = Response(
                "The mobile number field is accepting 10 digits only. Please provide a valid mobile number.",
                status=401,
                content_type='application/json')
            return error_response
        # Handle the uploaded resume
        resume = request.httprequest.files.get('attachment_id')
        resume_data = None
        if resume:
            resume_name = resume.filename
            resume_data = resume.read()

        # Find the user by name
        user_name = "Referral"
        user = request.env['res.users'].sudo().search([('name', '=', user_name)], limit=1)

        # Create a new hr.referral record with the extracted data
        applicant_data = {
            'name': name,
            'email': email,
            'mobile_number': mobile_number,
            'linkedin': linkedin,
            'attachment_id': [(0, 0, {
                'name': resume_name,
                'res_model': 'hr.form',
                'res_id': 0,
                'type': 'binary',
                'mimetype': 'application/pdf',
                'datas': base64.b64encode(resume_data),
            })] if resume_data else [],
            'user_id': user.id if user else False,
        }

        applicant = request.env['hr.form'].sudo().create(applicant_data)

        # Continue with any additional actions or responses
        # For example, you can display a thank-you message
        return request.render("hr_recruitment.application_thanks", {})    
    
class CandidateWebsiteFormController(http.Controller):
    @http.route('/candidate/', type='http', auth="public", website=True)
    def website_form(self, **post):
        # Render the form template again
        return http.request.render('hr_recruitment.web_form')

    @http.route('/candidate/website_thanks/', type='http', auth='public', website=True)
    def candidate_website_thanks(self, **post):
        # Only process if it's a POST request
        if request.httprequest.method == 'POST':
            # Extract data from the form submission
            candidate_name = post.get('candidate_name')
            candidate_email = post.get('candidate_email')
            residing_metro_manila = post.get('residing_metro_manila')
            relocate = post.get('relocate')
            obligatory_appointments = request.httprequest.form.getlist('obligatory_appointments')
            appointments_specification = post.get('appointments_specification')
            diagnosed = post.get('diagnosed')
            medical_condition = post.get('medical_condition')

            # Convert the selected IDs to integers (if needed)
            obligatory_appointments = [int(x) for x in obligatory_appointments]
                
            specification_ids = [(6, 0, obligatory_appointments)]
            
            # Create a new hr.candidate record with the extracted data
            candidate_data = {
                'name': candidate_name,
                'email': candidate_email,
                'residing_metro_manila': residing_metro_manila,
                'relocate': relocate,
                'specification_ids': specification_ids,
                'appointments_specification': appointments_specification,
                'diagnosed': diagnosed,
                'medical_condition': medical_condition,
            }
            candidate = http.request.env['hr.candidate'].sudo().create(candidate_data)

            # Continue with any additional actions or responses
            # For example, you can display a thank-you message
            return request.redirect('/candidate/thank_you/')
        else:
            # Handle non-POST requests
            return request.redirect('/candidate/')

class SurveyCodeValidation(http.Controller):
    @http.route('/check_survey_code', type='json', auth='public', methods=['POST'], csrf=False)
    def check_survey_code(self, survey_code):
        survey_record = request.env['hr.applicant'].sudo().search([('survey_code', '=', survey_code)], limit=1)
        
        # Check if the record exists
        if survey_record:
            return {
                'exists': True,
                'candidate_name': survey_record.partner_name,
                'candidate_email': survey_record.email_from
            }
        else:
            return {'exists': False}
