# -*- coding: utf-8 -*-
import logging

from odoo import fields, models, api, _

_logger = logging.getLogger(__name__)

shipment_states = [('ACCEPTED', 'Accepted'),
                   ('AT_SENDING_DEPOT', 'At sending depot'),
                   ('ON_THE_ROAD', 'On the road'),
                   ('AT_DELIVERY_DEPOT', 'At the delivery depot'),
                   ('DELIVERED', 'Delivered')]


class StockPickingParcel(models.Model):
    _name = 'stock.picking.parcel'
    name = fields.Char(
        string='Reference',
    )
    picking_id = fields.Many2one(
        comodel_name='stock.picking',
        string='Picking'
    )
    weight = fields.Float(
        string='Weight'
    )


class StockPicking(models.Model):
    _inherit = 'stock.picking'
    dpd_label_name = fields.Char(
        string='DPD Label File Name',
        copy=False
    )
    dpd_label_bin = fields.Binary(
        string='DPD Label',
        copy=False
    )
    dpd_parcel_ids = fields.One2many(
        comodel_name='stock.picking.parcel',
        inverse_name='picking_id',
        string='Parcels'
    )
    number_of_packages = fields.Integer(
        default=1
    )
    dpd_delivery_info_ids = fields.One2many(
        comodel_name='stock.picking.delivery',
        inverse_name='picking_id',
        string='Delivery information',
    )
    delivery_state = fields.Selection(
        selection=[('ACCEPTED', 'Accepted'),
                   ('AT_SENDING_DEPOT', 'At sending depot'),
                   ('ON_THE_ROAD', 'On the road'),
                   ('AT_DELIVERY_DEPOT', 'At the delivery depot'),
                   ('DELIVERED', 'Delivered')],
        string='Delivery state',
        default=None,
    )

    @api.multi
    def create(self, vals):
        picking = super(StockPicking, self).create(vals)
        # if the delivery carrier is dpd_be also generate the parcels
        if picking.carrier_id.delivery_type == 'dpd_be':
            picking.onchange_number_of_packages()
        return picking

    @api.multi
    def write(self, vals):
        picking = super(StockPicking, self).write(vals)
        for picking in self:
            # if the delivery carrier is dpd_be also generate the parcels
            if picking.carrier_id.delivery_type == 'dpd_be' and vals.get(
                    'carrier_id'):
                picking.onchange_number_of_packages()
        return picking

    @api.onchange('number_of_packages')
    def onchange_number_of_packages(self):
        new_parcels = []
        weight = self.number_of_packages == 1 and self.weight or 0
        for x in range(1, self.number_of_packages + 1):
            parcel_name = '%s-%s-%s' % (self.origin, self.name, x)
            new_parcels.append((0, 0, {'name': parcel_name,
                                       'weight': weight
                                       }))
        self.update({'dpd_parcel_ids': new_parcels})

    @api.multi
    def action_get_tracking(self):
        for picking in self:
            picking.carrier_id.get_tracking_information(picking)

    @api.multi
    def update_tracking_information(self, data):
        self.ensure_one()
        _logger.info("Synchronisation for picking:%s/%s" % (self.origin,
                                                            self.name))
        delivery_info = []
        vals = {}
        for line in data:
            # if the status has not been reached yet then
            # don't log the data
            if not line.get('reached'):
                continue
            # if this is not the current status, check if we have
            # this info in the log otherwise continue
            recs = self.dpd_delivery_info_ids.filtered(
                lambda r: r.state == line.get('state'))
            if not recs:
                delivery_info.append((0, 0, line))
            else:
                # DPD removes this info after state has been reached
                if line.get('date', False) == '':
                    del line['date']
                if line.get('location', False) == '':
                    del line['location']
                recs.update(line)
            # if this is the current state then also update the
            # delivery state of the picking
            if line.get('current') and self.delivery_state != line.get(
                    'state'):
                vals['delivery_state'] = line.get('state')
                trans_state = dict(shipment_states).get(line.get('state'))
                msg = _(
                    "Shipment state changed to: %s") % trans_state
                self.message_post(body=msg)

        vals.update({'dpd_delivery_info_ids': delivery_info})
        self.update(vals)
        return True

    @api.model
    def _check_delivery_synchro(self):
        # Get all the recs which are send by dpd, which have
        # optained a tracking reference and which are not yet delivered
        self.search(
            [('carrier_id.delivery_type', '=', 'dpd_be'),
             ('carrier_tracking_ref', '!=', False),
             ('delivery_state', '!=', 'DELIVERED')]).action_get_tracking()
        return True


class StockPickingDelivery(models.Model):
    _name = 'stock.picking.delivery'
    name = fields.Char(
        string='Name',
    )
    picking_id = fields.Many2one(
        comodel_name='stock.picking',
        string='Picking',
    )
    state = fields.Selection(
        selection=[('ACCEPTED', 'Accepted'),
                   ('AT_SENDING_DEPOT', 'At sending depot'),
                   ('ON_THE_ROAD', 'On the road'),
                   ('AT_DELIVERY_DEPOT', 'At the delivery depot'),
                   ('DELIVERED', 'Delivered')],
        string='Delivery state',
    )
    reached = fields.Boolean(
        string='Reached',
    )
    current = fields.Boolean(
        string='Current',
    )
    location = fields.Char(
        string='Location',
    )
    date = fields.Char(
        string='Date',
    )
    extra_info = fields.Text(
        string='Extra information',
    )
