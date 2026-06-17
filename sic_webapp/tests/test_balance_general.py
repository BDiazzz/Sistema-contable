from django.test import TestCase, Client
from django.urls import reverse
from decimal import Decimal
from sic_webapp.models import (
    CuentaPrincipal, SubCuenta, PeriodoContable, Transaccion, Movimiento
)
from django.utils import timezone
from datetime import timedelta


class BalanceGeneralClosedTests(TestCase):
    def setUp(self):
        # Cliente de pruebas
        self.client = Client()

        # Crear periodo cerrado
        today = timezone.now().date()
        # Usar fechas distintas para evitar la restricción unique en fecha_fin
        closed_date = today - timedelta(days=2)
        open_start = today - timedelta(days=3)
        open_end = today - timedelta(days=1)

        self.periodo = PeriodoContable.objects.create(
            nombre='Periodo Test',
            fecha_inicio=closed_date,
            fecha_fin=closed_date,
            estado='CERRADO'
        )
        # Crear además un periodo ABIERTO que cubra la fecha del periodo cerrado para que Transaccion.save() no falle
        self.periodo_abierto = PeriodoContable.objects.create(
            nombre='Periodo Abierto Temporal',
            fecha_inicio=open_start,
            fecha_fin=open_end,
            estado='ABIERTO'
        )

        # Crear cuentas principales
        self.cp_activo = CuentaPrincipal.objects.create(codigo='A', nombre='Activos')
        self.cp_pasivo = CuentaPrincipal.objects.create(codigo='P', nombre='Pasivos')
        self.cp_patr = CuentaPrincipal.objects.create(codigo='C', nombre='Capital')

        # Crear subcuentas
        self.sub_a1 = SubCuenta.objects.create(codigo='A101', nombre='Caja', cuenta_principal=self.cp_activo)
        self.sub_p1 = SubCuenta.objects.create(codigo='P201', nombre='Proveedores', cuenta_principal=self.cp_pasivo)
        self.sub_c1 = SubCuenta.objects.create(codigo='C301', nombre='Capital Social', cuenta_principal=self.cp_patr)

        # Crear transacciones y movimientos asociadas al periodo (usar el mismo Transaccion para simplicidad)
        # Crear transacción (se asignará inicialmente al periodo ABIERTO por la lógica del modelo)
        t1 = Transaccion.objects.create(fecha=closed_date, descripcion='T1 prueba')
        # Forzar asignación al periodo cerrado para la prueba (usamos update_fields para evitar reasignación automática)
        t1.periodo = self.periodo
        t1.save(update_fields=['periodo'])
        # Movimientos: Activo (Debe) +1000, Pasivo (Haber) +600, Patrimonio (Haber) +400 => cuadrará
        Movimiento.objects.create(transaccion=t1, subcuenta=self.sub_a1, tipo_movimiento='Debe', tipo_registro='NORMAL', monto=Decimal('1000.00'))
        Movimiento.objects.create(transaccion=t1, subcuenta=self.sub_p1, tipo_movimiento='Haber', tipo_registro='NORMAL', monto=Decimal('600.00'))
        Movimiento.objects.create(transaccion=t1, subcuenta=self.sub_c1, tipo_movimiento='Haber', tipo_registro='NORMAL', monto=Decimal('400.00'))

    def test_balance_calculation(self):
        url = reverse('balance_general_cerrado')
        response = self.client.get(url, {'periodo': self.periodo.pk})
        self.assertEqual(response.status_code, 200)

        ctx = response.context
        # Totales calculados por la vista
        total_activos = ctx.get('activos_total')
        total_pasivos = ctx.get('pasivos_total')
        total_patrimonio = ctx.get('patrimonio_total')

        self.assertIsNotNone(total_activos)
        self.assertIsNotNone(total_pasivos)
        self.assertIsNotNone(total_patrimonio)

        # Deben coincidir con lo creado: Activos=1000, Pasivos=600, Patrimonio=400
        self.assertEqual(Decimal('1000.00'), total_activos)
        self.assertEqual(Decimal('600.00'), total_pasivos)
        self.assertEqual(Decimal('400.00'), total_patrimonio)

        # La diferencia debe ser 0
        diff = total_activos - (total_pasivos + total_patrimonio)
        self.assertEqual(diff, Decimal('0.00'))

    def test_export_csv_contains_totals(self):
        url = reverse('balance_general_cerrado')
        response = self.client.get(url, {'periodo': self.periodo.pk, 'export': 'csv'})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # Revisar que incluya los totales y los rótulos
        self.assertIn('ACTIVOS', content)
        self.assertIn('PASIVOS', content)
        self.assertIn('PATRIMONIO', content)
        self.assertIn('Total Activos', content)
        self.assertIn('Total Pasivos', content)
        self.assertIn('Total Patrimonio', content)
        # Totales numéricos
        self.assertIn('1000.00', content)
        self.assertIn('600.00', content)
        self.assertIn('400.00', content)
