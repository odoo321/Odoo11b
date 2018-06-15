import logging
import math
from datetime import datetime, timedelta

import requests
from lxml import etree
from zeep import Client, exceptions as zeep_exceptions

from odoo import fields, models, api, exceptions, _
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)
price_types = [('fixed', 'Fixed price '),
               ('customer_price', 'Customer price')
               ]

dpd_mapping = {
    'getAuth': {
        'stage-url': 'https://public-dis-stage.dpd.nl/Services/'
                     'LoginService.svc?singlewsdl',
        'life-url': 'https://public-dis.dpd.nl/Services/'
                    'LoginService.svc?singlewsdl',
        'SOAPAction': "http://dpd.com/common/service/"
                      "LoginService/2.0/getAuth",
        'errorcode': "errorCode",
        'errormessage': "errorMessage",
    },
    'storeOrders': {
        'stage-url': 'https://public-dis-stage.dpd.nl/Services/'
                     'ShipmentService.svc?singlewsdl',
        'life-url': 'https://public-dis.dpd.nl/Services/'
                    'ShipmentService.svc?singlewsdl',
        'SOAPAction': 'http://dpd.com/common/service/'
                      'ShipmentService/3.1/storeOrders',
        'errorcode': "faultcode",
        'errormessage': "Message",
    },
    'getTrackingData': {
        'stage-url': 'https://public-dis-stage.dpd.nl/Services/'
                     'ParcelLifeCycleService.svc?singlewsdl',
        'life-url': 'https://public-dis.dpd.nl/Services/'
                    'ParcelLifeCycleService.svc?singlewsdl',
        'SOAPAction': 'http://dpd.com/common/service/'
                      'ParcelLifeCycleService/2.0/getTrackingData',
        'errorcode': "errorCode",
        'errormessage': "errorMessage",
    },
    'findParcelShopsByGeoData': {
        'stage-url': 'https://public-dis-stage.dpd.nl/Services/'
                     'ParcelShopFinderService.svc?singlewsdl',
        'life-url': 'https://public-dis.dpd.nl/Services/'
                    'ParcelShopFinderService.svc?singlewsdl',
        'SOAPAction': 'http://dpd.com/common/service/'
                      'ParcelShopFinderService/3.0/findParcelShopsByGeoData',
        'errorcode': "faultCodeField",
        'errormessage': "messageField",
    }
}


def get_data(nd, fld):
    att_value = nd.find(fld)
    if att_value is not None and att_value.text is not None:
        return att_value.text
    return ''


def get_dpd_weight(weight):
    return math.trunc(weight * 100)


class ProviderDPDBE(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(
        selection_add=[('dpd_be', "DPD")],
    )

    dpd_delis_id = fields.Char(
        string="Delis-Id",
        groups="base.group_system",
        help="Your Delis Id",
    )
    dpd_password = fields.Char(
        string="Password",
        groups="base.group_system",
        help="Your Password",
    )
    dpd_label_size = fields.Selection(
        selection=[('A4', 'A4'), ('A6', 'A6')],
        string='PDF Format Size',
        default='A4',
    )
    dpd_ship_service = fields.Selection(
        selection=[('normal', 'Normal'),
                   ('Shop_Delivery', 'Shop delivery')],
        string='DPD Ship Service',
        default='normal',
    )
    dpd_shipping_type = fields.Selection(
        selection=[('CL', 'Classic'),
                   ('E10', 'Express 10h'),
                   ('E12', 'Express 12h'),
                   ('E18', 'Express 18h'),
                   ('Shop_Delivery', 'Shop delivery')],
        string='DPD Shipping Type',
        default='CL',
    )
    dpd_shipping_cost = fields.Float(
        string='Fixed Shipping Cost',
        help='As DPD doesnot provide the shipping cost, you can manually '
             'specify the shipping price here.',
    )
    dpd_customer_uid = fields.Char(
        string='Customer UID'
    )
    dpd_token = fields.Char(
        string='Token'
    )
    dpd_depot = fields.Char(
        string='Depot'
    )
    dpd_login_date = fields.Datetime(
        string='Login date'
    )
    dpd_auto_sync_delivery = fields.Boolean(
        string='Automatic delivery synchronistion',
        help='You can turn the automatic delivery synchronisation on '
             'The delivery state of your parcel will synchronise with DPD '
             'automaticly',
    )
    dpd_shipping_cost_type = fields.Selection(
        selection=[('fixed', 'Fixed'),
                   ('base_on_rule', 'Based on rules'),
                   ('base_product', 'Based on attached product'),
                   ],
        string='Shipping cost calculation',
        default='fixed'
    )

    @api.onchange('dpd_auto_sync_delivery')
    def onchange_dpd_auto_sync_delivery(self):
        self.env.ref('delivery_dpd_be.'
                     'ir_cron_delivery_synchronisation').write(
            {'active': self.dpd_auto_sync_delivery})

    def dpd_be_rate_shipment(self, order):
        '''

        :param orders:
        :return: {'success': boolean,
                   'price': a float,
                   'error_message': a string containing an error message,
                   'warning_message': a string containing a warning message}
        '''
        res = {'success': True,
               'price': 0.0,
               'error_message': False,
               'warning_message': False}
        # Pass pricelist id to product
        carrier = self.with_context(
            pricelist=order.pricelist_id.id)._match_address(
            order.partner_shipping_id)
        if not carrier:
            res['error_message'] = _('No carrier matching.')
            res['success'] = False

        if order.carrier_id.dpd_shipping_cost_type == 'fixed':
            res['price'] = order.carrier_id.fixed_price or 0.0
        elif carrier.dpd_shipping_cost_type == 'base_product':
            res['price'] = order.carrier_id.product_id.price or 0.0
        else:
            # price calculation based on rules
            try:
                computed_price = order.carrier_id.get_price_available(order)
                res['price'] = computed_price
            except exceptions.UserError as e:
                # No suitable delivery method found,
                # probably configuration error
                res['error_message'] = e.name
                _logger.info("Carrier %s: %s", order.carrier_id.name, e.name)
        return res

    def get_sender_recipient(self, partner):
        return {
            'name1': partner.name,
            'street': partner.street,
            # 'houseNo': houseno,
            'zipCode': partner.zip,
            'city': partner.city,
            'state': partner.state_id.name,
            'country': partner.country_id.code,
        }

    def get_order(self, picking):
        return {
            'generalShipmentData':
                {'sendingDepot': self.dpd_depot,
                 'product': self.dpd_shipping_type,
                 'sender': self.get_sender_recipient(
                     picking.picking_type_id.warehouse_id.partner_id),
                 'recipient': self.get_sender_recipient(
                     picking.partner_id),
                 },
            'parcels': self.get_parcels(picking=picking),
            'productAndServiceData': {
                'orderType': 'consignment'}
        }

    def get_parcels(self, picking):
        parcels = []
        for line in picking.dpd_parcel_ids:
            parcel = {
                'customerReferenceNumber1': line.name,
                'weight': get_dpd_weight(line.weight),
            }
            parcels.append(parcel)
        return parcels

    def get_print_options(self):
        return {
            'printerLanguage': 'PDF',
            'paperFormat': self.dpd_label_size,
        }

    def get_soap_headers(self):
        return {
            'authentication':
                {
                    'delisId': self.dpd_delis_id,
                    'authToken': self.dpd_token,
                    'messageLanguage': self.env.user.lang
                }
        }

    def dpd_be_send_shipping(self, pickings):
        '''

        :param pickings:
        :return list: A list of dictionaries (one per picking) containing of the form::
                         { 'exact_price': price,
                           'tracking_number': number }
                           # TODO missing labels per package
                           # TODO missing currency
                           # TODO missing success, error, warnings
        '''
        successfull, error = self.login()
        if not successfull:
            raise exceptions.AccessError(error)

        res = []
        for picking in pickings:
            shipping_data = {
                'tracking_number': "",
                'exact_price': 0.0
            }
            try:
                order = self.get_order(picking=picking)

                action = 'storeOrders'
                client = Client(self.dpd_get_url(action=action))

                request = client.service._binding.create_message(
                    action,
                    printOptions=self.get_print_options(),
                    order=order,
                    _soapheaders=self.get_soap_headers())

                error, response = self.dpd_send_message(action=action,
                                                        request=request)
                if error:
                    raise exceptions.AccessError(error)

                node = etree.fromstring(response.content)
                pl_pdf = node.xpath('//parcellabelsPDF')[0].text
                pl_num = node.xpath('//parcelLabelNumber')[0].text

                picking.dpd_label_bin = pl_pdf
                picking.dpd_label_name = '%s.pdf' % picking.name
                shipping_data.update({'tracking_number': pl_num})

            except zeep_exceptions.Fault as zeep_exception:
                errorcode = zeep_exception.detail[0][0].text
                errormessage = zeep_exception.detail[0][1].text
                if errorcode:
                    logmessage = "An error occured."
                    logmessage += "\nFull Response:%s\n" % errormessage
                else:
                    logmessage = "An error occured."
                    logmessage += "\nCode:%s\n" % zeep_exception.code
                    logmessage += "\nMessage:%s\n" % zeep_exception.message
                raise exceptions.ValidationError(logmessage)

            res = res + [shipping_data]
        return res

    def dpd_be_get_tracking_link(self, picking):
        self.ensure_one()
        res = ""
        if picking.carrier_tracking_ref:
            res = "https://tracking.dpd.de/parcelstatus?" \
                  "query=%s &trackig=Track" % picking.carrier_tracking_ref
        return res

    def dpd_be_cancel_shipment(self, picking):
        raise exceptions.ValidationError(
            _('Shipment can not be cancelled anymore.'))
        return True

    def dpd_send_message(self, action, request):
        error = False
        encoded_request = etree.tostring(request, encoding='utf-8')
        headers = {
            "Content-Type": "text/xml; charset=UTF-8",
            "Content-Length": str(len(encoded_request)),
            "SOAPAction": dpd_mapping.get(action).get('SOAPAction')
        }

        response = requests.post(url=self.dpd_get_url(action=action),
                                 headers=headers,
                                 data=encoded_request)
        if response.status_code != 200:
            try:
                node = etree.fromstring(response.content)
                expr = '//*[local-name()=$name]'
                errorcode = node.xpath(expr, name=dpd_mapping.get(action).get(
                    'errorcode'))[0].text
                errormessage = \
                    node.xpath(expr, name=dpd_mapping.get(action).get(
                        'errormessage'))[0].text
                error = 'Error: %s\nError message: %s' % (errorcode,
                                                          errormessage)
            except:
                _logger.info(encoded_request)
                node = etree.fromstring(response.content)
                _logger.info(etree.tostring(node, pretty_print=True))
                error = 'An error has occured'
        return error, response

    def dpd_get_url(self, action):
        return dpd_mapping.get(action).get(
            '%s-url' % (self.prod_environment and 'life' or 'stage'))

    @api.multi
    def login(self, force=False):
        '''
        Login to DPD server
        :param force:
        :return: succeeded: True/False, error: Errormessage/False
        '''
        # Check if last login was more then 24h ago
        # Dpd accepts max 2 logins per 24h
        dpd_login_date = fields.Datetime.from_string(
            self.dpd_login_date)
        if dpd_login_date:
            dpd_login_date += timedelta(hours=24)

        if not force and dpd_login_date and dpd_login_date > datetime.now():
            return True, False

        try:
            action = 'getAuth'
            client = Client(self.dpd_get_url(action=action))

            request = client.service._binding.create_message(
                action,
                delisId=self.dpd_delis_id,
                password=self.dpd_password,
                messageLanguage=self.env.user.lang)

            error, response = self.dpd_send_message(action=action,
                                                    request=request)
            if error:
                return False, error

            node = etree.fromstring(response.content)
            res_node = node.xpath('//return')[0]
            cUId = get_data(res_node, 'customerUid')
            depot = get_data(res_node, 'depot')
            token = get_data(res_node, 'authToken')

            self.write({'dpd_customer_uid': cUId,
                        'dpd_depot': depot,
                        'dpd_token': token,
                        'dpd_login_date': datetime.now()})

        except zeep_exceptions.Fault as zeep_exception:
            return zeep_exception.detail[0][1].text

        return True, False

    @api.multi
    def action_test_connection(self):
        successfull, error = self.login(force=True)
        if not successfull:
            raise exceptions.AccessError(error)

        return self.env.ref('delivery_dpd_be.'
                            'action_wizard_test_connection').read()[0]

    @api.multi
    def get_tracking_information(self, picking):
        # Try to login to DPD
        successfull, error = self.login()
        if not successfull:
            raise exceptions.AccessError(error)

        try:
            action = 'getTrackingData'
            client = Client(self.dpd_get_url(action=action))

            request = client.service._binding.create_message(
                action,
                parcelLabelNumber=picking.carrier_tracking_ref,
                _soapheaders=self.get_soap_headers()
            )

            error, response = self.dpd_send_message(action=action,
                                                    request=request)
            if response.status_code == 200:
                node = etree.fromstring(response.content)
                states = []
                for status_info in node.xpath('//statusInfo'):
                    reached = get_data(status_info, 'statusHasBeenReached')
                    status = get_data(status_info, 'status')
                    current = get_data(status_info, 'isCurrentStatus')
                    location = get_data(status_info, 'location/content')
                    date = get_data(status_info, 'date/content')
                    info = get_data(status_info,
                                    'description/content/content')
                    state = {'state': status,
                             'reached': reached == 'true',
                             'current': current == 'true',
                             'location': location,
                             'date': date,
                             'extra_info': ''}
                    infos = [info]
                    for extra_info in status_info.xpath(
                            'importantItems/content'):
                        infos.append(get_data(extra_info, 'content'))
                    state['extra_info'] = '/'.join(infos)
                    states.append(state)

                picking.update_tracking_information(data=states)

            if error:
                return error

        except zeep_exceptions.Fault as zeep_exception:
            errorcode = zeep_exception.detail[0][0].text
            errormessage = zeep_exception.detail[0][1].text
            if errorcode:
                logmessage = "An error occured."
                logmessage += "\nFull Response:%s\n" % errormessage
            else:
                logmessage = "An error occured."
                logmessage += "\nCode:%s\n" % zeep_exception.code
                logmessage += "\nMessage:%s\n" % zeep_exception.message
            raise exceptions.ValidationError(logmessage)

        return True

    def get_price_from_picking(self, total, weight, volume, quantity):
        # Overruled this method to implement variable_factor='per_quantity'
        price = 0.0
        criteria_found = False
        price_dict = {'price': total, 'volume': volume, 'weight': weight,
                      'wv': volume * weight, 'quantity': quantity}
        for line in self.price_rule_ids:
            test = safe_eval(
                line.variable + line.operator + str(
                    line.max_value), price_dict)
            if test:
                base_price = line.list_base_price
                if line.price_type != 'fixed':
                    # get the customer price
                    base_price = line.carrier_id.product_id.price

                if line.variable_factor != 'per_quantity':
                    price = \
                        base_price + line.list_price * price_dict[
                            line.variable_factor]
                    criteria_found = True
                    break
                else:
                    price = \
                        (base_price + line.list_price) * math.ceil(
                            (price_dict['quantity'] /
                             line.quantity_per_value))
                    criteria_found = True
                    break

        if not criteria_found:
            raise exceptions.UserError(_("Selected product in the delivery "
                                         "method doesn't fulfill any of "
                                         "the delivery carrier(s) criteria."))

        return price


class PriceRule(models.Model):
    _inherit = "delivery.price.rule"

    @api.depends('variable', 'operator', 'max_value', 'list_base_price',
                 'list_price', 'variable_factor')
    def _get_name(self):
        for rule in self:
            name = 'if %s %s %s then' % (rule.variable,
                                         rule.operator,
                                         rule.max_value)
            # Sets or the list_base_price when fixed, or the customer price
            name = '%s %s%s + ' % (name,
                                   rule.variable_factor == 'per_quantity'
                                   and '(' or '', rule.price_type != 'fixed'
                                   and dict(price_types).get(rule.price_type)
                                   or rule.list_base_price)

            # if a variable factor is set generate text for that
            if rule.variable_factor:
                var_factor = rule.variable_factor
                if rule.variable_factor == 'per_quantity':
                    var_factor = '%s %s)' % (_('Per quantity of '),
                                             rule.quantity_per_value)
                beg_fact = "("
                end_fact = ")"
                if rule.variable_factor == 'per_quantity':
                    beg_fact = end_fact = ""
                var_factor = '%s%s times %s%s Extra' % (beg_fact,
                                                        rule.list_price,
                                                        var_factor,
                                                        end_fact)
                name = '%s %s' % (name, var_factor)

            rule.name = name

    variable_factor = fields.Selection(
        selection_add=[('per_quantity', 'Per Quantity of ')],
    )
    quantity_per_value = fields.Float(
        string='Per Quantity of',
    )
    price_type = fields.Selection(
        selection=price_types,
        default='fixed',
        string='Price type',
        help="Fixed price: a fixed price, "
             "Customer price: calculated based on pricelists."
    )
