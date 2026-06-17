from django import forms
from django.forms import modelformset_factory, DecimalField
from django.db import models
from django.db.models.functions import Cast, Substr
from .models import Transaccion, Movimiento, SubCuenta
from decimal import Decimal

# --- Formulario para el Modelo Movimiento ---
class MovimientoForm(forms.ModelForm):
    subcuenta = forms.ModelChoiceField(
        queryset=SubCuenta.objects.annotate(
            prefijo=Substr('codigo', 1, 1),
            numero=Cast(Substr('codigo', 2), models.IntegerField())
        ).order_by('prefijo', 'numero'),
        label='Subcuenta Contable',
        to_field_name='codigo', 
        empty_label="--- Seleccionar Subcuenta ---",
        error_messages={
            'required': 'Debes elegir una subcuenta.',
            'invalid_choice': 'La subcuenta seleccionada no es válida.'
        }
    )
    
    monto = forms.DecimalField(
        max_digits=15, 
        decimal_places=2,
        label='Monto',
        min_value=Decimal('0.01'),
        error_messages={
            'required': 'Ingresa un monto.',
            }
    )
    

    class Meta:
        model = Movimiento
        fields = ['subcuenta', 'tipo_movimiento', 'tipo_registro', 'monto']


# --- Formset para los Movimientos ---
MovimientoFormSet = modelformset_factory(
    Movimiento,
    form=MovimientoForm,
    fields=('subcuenta', 'tipo_movimiento', 'monto'),
    extra=1, 
    can_delete=True
)


# --- Formulario para el Modelo Transaccion ---
class TransaccionForm(forms.ModelForm):
    class Meta:
        model = Transaccion
        fields = ['fecha', 'descripcion']
        widgets = {
            'fecha': forms.DateInput(attrs={
                'type': 'date', 
                'class': 'form-control', 
                'readonly': True
            }),
            'descripcion': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }
        labels = {
            'fecha': 'Fecha del Asiento',
            'descripcion': 'Concepto de la Transacción',
        }
