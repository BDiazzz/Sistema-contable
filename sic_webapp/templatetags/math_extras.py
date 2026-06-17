from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()


@register.filter
def subtract(value, arg):
     """Resta arg de value usando Decimal para mantener precisión monetaria.

     Uso en plantilla: {{ a|subtract:b|floatformat:2 }}
     """
     try:
         if value is None:
             a = Decimal('0.00')
         elif isinstance(value, Decimal):
             a = value
         else:
             a = Decimal(str(value))

         if arg is None:
             b = Decimal('0.00')
         elif isinstance(arg, Decimal):
             b = arg
         else:
             b = Decimal(str(arg))

         return a - b
     except (InvalidOperation, TypeError):
         return Decimal('0.00')


@register.filter
def abs_value(value):
     """Retorna el valor absoluto (positivo) de un número.

     Uso en plantilla: {{ valor|abs_value|floatformat:2 }}
     """
     try:
         if value is None:
             return Decimal('0.00')
         elif isinstance(value, Decimal):
             return abs(value)
         else:
             return abs(Decimal(str(value)))
     except (InvalidOperation, TypeError, ValueError):
         return Decimal('0.00')


@register.filter
def format_codigo(value):
     """Formatea un código de cuenta agregando un guion entre la letra y el número.
     
     Uso en plantilla: {{ subcuenta.codigo|format_codigo }}
     """
     if not value:
         return value
     
     import re
     match = re.match(r'^([A-Za-z]+)(\d+)$', str(value))
     if match:
         letra = match.group(1)
         numero = match.group(2)
         return f"{letra}-{numero}"
     
     return value
