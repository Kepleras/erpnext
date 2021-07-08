# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_link_to_form, today, flt
from frappe.model.document import Document

class FullAndFinalStatement(Document):

	def validate(self):
		self.get_outstanding_statements()
		if self.docstatus == 1:
			self.validate_settlement('payables')
			self.validate_settlement('receivables')

	def validate_settlement(self, type):
		for data in self.get(type,[]):
			if data.status == "Unsettled":
				frappe.throw(_("Settled all Payables and Receivable before submission"))


	@frappe.whitelist()
	def get_outstanding_statements(self):
		if self.relieving_date:
			if not len(self.get("payables", [])):
				components = self.get_payable_component()
				self.create_component_row(components, "payables")
			if not len(self.get("receivables", [])):
				components = self.get_receivable_component()
				self.create_component_row(components, "receivables")

			if not len(self.get("assets_allocated", [])):
				for data in self.get_assets_movement():
					self.append("assets_allocated", data)
		else:
			frappe.throw(_("Set Relieving Date for Employee: {0}").format(get_link_to_form("Employee", self.employee)))

	def create_component_row(self, components, type):
		data = {}
		for component in components:
			data["status"] = "Unsettled"
			data["component"] = component
			self.append(type, data)


	def get_payable_component(self):
		return [
			"Salary Slip",
			"Gratuity",
			"Expense Claim",
			"Bonus",
			"Leave Encashment",
		]

	def get_receivable_component(self):
		return [
			"Loans",
			"Employee Advance",
		]

	def get_assets_movement(self):
		asset_movements = frappe.get_all("Asset Movement Item",
			filters = {"docstatus": 1},
			fields = ["asset", "from_employee", "to_employee", "parent", "asset_name"],
			or_filters = {
				"from_employee": self.employee,
				"to_employee": self.employee
			}
		)

		data = []
		inward_movements = []
		outward_movements = []
		for movement in asset_movements:
			if movement.to_employee and movement.to_employee == self.employee:
				inward_movements.append(movement)

			if movement.from_employee and movement.from_employee == self.employee:
				outward_movements.append(movement)

		for movement in inward_movements:
			outwards_count = [movement.asset for movement in outward_movements].count(movement.asset)
			inwards_counts = [movement.asset for movement in inward_movements].count(movement.asset)

			if inwards_counts > outwards_count:
				data.append({
					"reference": movement.parent,
					"asset_name": movement.asset_name,
					"date": frappe.db.get_value("Asset Movement", movement.parent, 'transaction_date'),
					"status": "Owned"
				})
		return data

	@frappe.whitelist()
	def create_journal_entry(self):
		precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")
		jv = frappe.new_doc("Journal Entry")
		jv.company = self.company
		jv.voucher_type = "Bank Entry"
		jv.posting_date = today()

		difference = self.total_payable_amount - self.total_receivable_amount

		for data in self.payables:
			if data.amount > 0 and not data.considered_in_salary_slip:
				account_dict = {
					"account": data.account,
					"debit_in_account_currency": flt(data.amount, precision)
				}
				if data.reference_document_type == "Expense Claim":
					account_dict["party_type"] = "Employee"
					account_dict["party"] = self.employee

				jv.append("accounts", account_dict)

		for data in self.receivables:
			if data.amount > 0:
				account_dict = {
					"account": data.account,
					"credit_in_account_currency": flt(data.amount, precision)
				}
				if data.reference_document_type == "Employee Advance":
					account_dict["party_type"] = "Employee"
					account_dict["party"] = self.employee

				jv.append("accounts", account_dict)

		jv.append("accounts", {
			"credit_in_account_currency": difference if difference > 0 else 0,
			"debit_in_account_currency": -(difference) if difference < 0 else 0,
			"reference_type": self.doctype,
			"reference_name": self.name
		})
		return jv

@frappe.whitelist()
def get_account_and_amount(ref_doctype, ref_document):
	if ref_doctype == "Salary Slip" and ref_document:
		payroll, amount = frappe.db.get_value("Salary Slip", ref_document, ["payroll_entry", "net_pay"])
		payable_account = frappe.db.get_value("Payroll Entry", payroll, "payroll_payable_account")
		return [payable_account, amount]

	if ref_doctype == "Gratuity" and ref_document:
		payable_account, amount = frappe.db.get_value("Gratuity", ref_document, ["payable_account", "amount"])
		return [payable_account, amount]

	if ref_doctype == "Expense Claim" and ref_document:
		details = frappe.db.get_value("Expense Claim", ref_document,
			["payable_account", "grand_total", "total_amount_reimbursed", "total_advance_amount"], as_dict=True)
		payable_account = details.payable_account
		amount = details.grand_total - (details.total_amount_reimbursed + details.total_advance_amount)
		return [payable_account, amount]

	if ref_doctype == "Loan" and ref_document:
		details = frappe.db.get_value("Loan", ref_document,
			['payment_account', 'total_payment', 'total_amount_paid'], as_dict=1)
		payment_account = details.payment_account
		amount = details.total_payment - details.total_amount_paid
		return [payment_account, amount]

	if ref_doctype == "Employee Advance" and ref_document:
		details = frappe.db.get_value("Employee Advance", ref_document,
			['advance_account','paid_amount', 'claimed_amount', 'return_amount'], as_dict = 1)
		payment_account = details.advance_account
		amount = details.paid_amount - (details.claimed_amount + details.return_amount)
		return [payment_account, amount]


