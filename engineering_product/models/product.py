# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

import re


class ProductCategory(models.Model):
    _inherit = "product.category"

    # products managed by engineering (used in production) should always have a valid default_code
    eng_management = fields.Boolean(
        string="Engineering Management",
        default=False,
        help="Products in this category are under engineering management.  "
             "They will require a valid Internal Reference code.")
    eng_code_sequence = fields.Many2one(
        string="Engineering Code Sequence",
        comodel_name="ir.sequence",
        help="Products created in this category will receive an engineering code from this sequence")
    default_rev = fields.Char(string="Default Revision")
    rev_delimiter = fields.Char(string="Revision Delimiter")
    def_code_regex = fields.Char(
        string="Product Code RegEx",
        help="Regular Expression to be used when validating product's Internal Reference.  "
             "Leave this field empty to accept any code format.")

    @api.constrains('eng_management', 'eng_code_sequence', 'default_rev', 'rev_delimiter', 'def_code_regex')
    def _validate_eng_management(self):
        if self.eng_management:
            if not self.eng_code_sequence or not self.default_rev or not self.rev_delimiter:
                raise ValidationError("With Engineering Management enabled, all management parameters are required")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    eng_management = fields.Boolean(related='categ_id.eng_management', readonly="1")
    rev_delimiter = fields.Char(related='categ_id.rev_delimiter', readonly="1")
    eco_ref = fields.Char(related='product_variant_ids.eco_ref')
    eng_code = fields.Char(
        string='Engineering Code',
        compute='_compute_eng_code',
        inverse='_set_eng_code',
        store=True)
    eng_rev = fields.Char(
        string='Engineering Revision',
        compute='_compute_eng_rev',
        inverse='_set_eng_rev',
        store=True)
    eng_categ_id = fields.Many2one(
        comodel_name='engineering.category',
        string='Engineering Category',
        domain="[('type','=','normal')]",
        help="Select category for the current product")
    deprecated = fields.Boolean(
        string='Deprecated',
        compute='_compute_deprecated',
        inverse='_set_deprecated',
        store=True,
        index=True)
    eng_notes = fields.Text(
        string='Engineering Notes',
        compute='_compute_eng_notes',
        inverse='_set_eng_notes')
    preparation = fields.Many2one(
        comodel_name='engineering.preparation',
        string='Prep')
    coating = fields.Many2one(
        comodel_name='engineering.coating',
        string='Coating')


    @api.constrains('eng_categ_id')
    def _validate_eng_cat(self):
        if self.eng_management:
            if not self.eng_categ_id:
                raise ValidationError("Engineering Category is required for this Product Category")
        return True

    @api.depends('product_variant_ids', 'product_variant_ids.eng_code')
    def _compute_eng_code(self):
        unique_variants = self.filtered(lambda template: len(template.product_variant_ids) == 1)
        for template in unique_variants:
            template.eng_code = template.product_variant_ids.eng_code
        for template in (self - unique_variants):
            template.eng_code = ''

    @api.one
    def _set_eng_code(self):
        if len(self.product_variant_ids) == 1:
            self.product_variant_ids.eng_code = self.eng_code

    @api.depends('product_variant_ids', 'product_variant_ids.eng_rev')
    def _compute_eng_rev(self):
        unique_variants = self.filtered(lambda template: len(template.product_variant_ids) == 1)
        for template in unique_variants:
            template.eng_rev = template.product_variant_ids.eng_rev
        for template in (self - unique_variants):
            template.eng_rev = ''

    @api.one
    def _set_eng_rev(self):
        if len(self.product_variant_ids) == 1:
            self.product_variant_ids.eng_rev = self.eng_rev

    @api.depends('product_variant_ids', 'product_variant_ids.deprecated')
    def _compute_deprecated(self):
        for template in self:
            template.deprecated = all([x.deprecated for x in template.product_variant_ids])

    @api.one
    def _set_deprecated(self):
        for variant in self.product_variant_ids:
            variant.deprecated = self.deprecated

    @api.depends('product_variant_ids', 'product_variant_ids.eng_notes')
    def _compute_eng_notes(self):
        unique_variants = self.filtered(lambda template: len(template.product_variant_ids) == 1)
        for template in unique_variants:
            template.eng_notes = template.product_variant_ids.eng_notes
        for template in (self - unique_variants):
            template.eng_notes = ''

    @api.one
    def _set_eng_notes(self):
        if len(self.product_variant_ids) == 1:
            self.product_variant_ids.eng_notes = self.eng_notes

    def button_revise(self, values=None):
        if len(self.product_variant_ids) == 1:
            self.product_variant_ids.button_revise(values)


class ProductProduct(models.Model):
    _inherit = "product.product"

    _sql_constraints = [('default_code_uniq', 'unique (default_code)', "Product Code must be unique."), ]

    default_code = fields.Char(
        compute='_get_eng_code',
        inverse='_set_eng_code',
        store=True)
    eng_code = fields.Char(
        string="Engineering Code",
        index=True,
        nocopy=True)
    eng_rev = fields.Char(
        string="Engineering Revision",
        nocopy=True)
    eco_ref = fields.Char(
        string="Engineering Change Order",
        nocopy=True,
        help="External ECO number")
    product_manager = fields.Many2one(
        comodel_name='res.users',
        related='product_tmpl_id.product_manager')
    deprecated = fields.Boolean(
        string='Deprecated',
        index=True)
    eng_notes = fields.Text('Engineering Notes')

    re_code = re.compile(r'^([_A-Z0-9-]+)\.([A-Z-][0-9])$')
    re_code_copy = re.compile(r'^((COPY\.)?[_A-Z0-9-]+\.[A-Z-][0-9])$')

    @api.depends('eng_code', 'eng_rev')
    def _get_eng_code(self):
        for prod in self:
            category = prod.product_tmpl_id.categ_id
            if prod.eng_code and category.eng_management:
                prod.default_code = prod.eng_code +\
                                    category.rev_delimiter +\
                                    prod.eng_rev

    @api.depends('default_code', 'eng_code', 'eng_rev')
    def _set_eng_code(self):
        for prod in self:
            if prod.product_tmpl_id.categ_id.eng_management:
                prod.eng_code, prod.eng_rev = prod._parse_default_code(
                    prod.default_code,
                    prod.product_tmpl_id.categ_id.def_code_regex
                )

    def _parse_default_code(self, default_code, def_code_regex):
        code_match = re.match(def_code_regex, default_code)
        res = code_match and (code_match.group(1), code_match.group(2)) or (False, False)
        return res

    @api.constrains('default_code', 'product_tmpl_id')
    def _validate_default_code(self):
        category = self.product_tmpl_id.categ_id
        if category.eng_management:
            if not self.default_code:
                raise ValidationError("Internal Reference code is required for this Engineering Category")
            if category.def_code_regex and not re.match(category.def_code_regex, self.default_code):
                raise ValidationError("Internal Reference code is not valid for this Engineering Category")
        return True

    @api.model
    def create(self, vals):
        if not (vals.get('eng_code') and vals.get('eng_rev')):
            cat = vals.get('categ_id') and self.env['product.category'].browse(vals['categ_id'])
            if not cat:
                tmpl = self.env['product.template'].browse(vals.get('product_tmpl_id'))
                cat = tmpl.categ_id
            if cat and cat.eng_management:
                if vals.get('default_code'):
                    vals['eng_code'], vals['eng_rev'] =\
                        self._parse_default_code(vals['default_code'], cat.def_code_regex)
                else:
                    # TODO: figure out why we are incrementing the sequence, when the user specifies a code
                    vals['eng_code'] = cat.eng_code_sequence.next_by_id()
                    vals['eng_rev'] = cat.default_rev
        product = super(ProductProduct, self.with_context(create_product_product=True)).create(vals)
        return product

    @api.multi
    def write(self, values):
        if not (values.get('eng_code', self.eng_code) and values.get('eng_rev', self.eng_rev)):
            cat = self.env['product.category'].browse(values.get('categ_id', self.categ_id.id))
            if cat.eng_management:
                if values.get('default_code'):
                    values['eng_code'], values['eng_rev'] = self._parse_default_code(values['default_code'], cat.def_code_regex)
                else:
                    values['eng_code'] = cat.eng_code_sequence.next_by_id()
                    values['eng_rev'] = cat.default_rev
        res = super(ProductProduct, self).write(values)
        return res

    @api.model
    def search(self, args, offset=0, limit=None, order=None, count=False):
        if self._context.get('search_default_eng_categ_id'):
            args.append((('eng_categ_id', 'child_of', self._context['search_default_eng_categ_id']), ))
        return super(ProductProduct, self).search(args, offset=offset, limit=limit, order=order, count=count)

    # TODO: create a revision wizard
    @api.multi
    def button_revise(self, values=None):
        """
        Best if called by a wizard where the user can specify a new rev
        """
        self.ensure_one()
        if values is None:
            values = {}

        # copy product
        defaults = {
            'name': self.name,
            'eng_code': self.eng_code,
            'eng_rev': 'Z9',
        }
        defaults.update(values)
        new_prod = self.copy(default=defaults)

        # copy orderpoints
        # orderpoints reference the product directly
        old_ops = self.env['stock.warehouse.orderpoint'].search([('product_id', '=', self.id)])
        for op in old_ops:
            op.copy(default={'product_id': new_prod.id})

        # domain for models referencing the template
        # if we copy a variant or create one, we keep the same template
        domain = []
        is_variant = False
        if new_prod.product_tmpl_id == self.product_tmpl_id:
            # this is a variant, so match only models related this product (not the template)
            domain.append(('product_id', '=', self.id))
            is_variant = True
        else:
            # not a variant, so match the template reference
            domain.append(('product_tmpl_id', '=', self.product_tmpl_id.id))

        # copy active boms
        # we may require product_id on mrp.bom, but for now, assume the product_id is only set for variants
        old_boms = self.env['mrp.bom'].search(domain)
        for bom in old_boms:
            defaults = {
                'product_tmpl_id': new_prod.product_tmpl_id.id,
                'product_id': bom.product_id and new_prod.id or False}
            bom.copy(default=defaults)

        # copy quality points
        old_qcs = self.env['quality.point'].search(domain)
        for qc in old_qcs:
            defaults = {
                'product_tmpl_id': new_prod.product_tmpl_id.id,
                'product_id': qc.product_id and new_prod.id or False}
            qc.copy(default=defaults)

        # copy sellers
        old_sellers = self.env['product.supplierinfo'].search(domain)
        for seller in old_sellers:
            defaults = {
                'product_tmpl_id': new_prod.product_tmpl_id.id,
                'product_id': seller.product_id and new_prod.id or False}
            seller.copy(default=defaults)

        # deprecate and set warnings on old revision
        self.deprecated = True
        self.purchase_line_warn = 'warning'
        self.purchase_line_warn_msg = 'This product has been revised'

        return new_prod.id
