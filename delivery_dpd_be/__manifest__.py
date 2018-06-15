# -*- coding: utf-8 -*-
{
    'name': 'DPD HOME delivery for BENELUX only',
    'version': '11.0.0.0.2',
    'author': "Jean-Paul Robineau",
    'category': 'Delivery',
    'summary': "DPD Delivery For BENELUX only",
    'depends': [
        'delivery',
        'sale',
        'stock',
    ],
    'description': """DPD Delivery For BENELUX only
""",
    'website': 'http://www.apertoso.be/',
    'data': [
        'security/ir.model.access.csv',
        'data/synchro_action_rule_data.xml',
        'views/delivery_dpd_view.xml',
        'views/picking_view.xml',
        'wizard/wizard_test_connection_view.xml',
    ],
    'demo': [
    ],
    'external_dependencies': {'python': ['zeep']},
    'license': 'OPL-1',
    'tests': [],
    'installable': True,
    'auto_install': False,
    'application': False,
    'currency': 'EUR',
    'images': ['static/description/dpd_home_delivery.png'],
    'price': 125
}
