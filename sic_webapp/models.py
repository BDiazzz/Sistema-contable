from django.db import models
from django.core.exceptions import ValidationError

# 1. CUENTA PRINCIPAL (Modelo para la AGRUPACIÓN, no lleva movimientos directos)
class CuentaPrincipal(models.Model):
    # Usamos el código como PK
    codigo = models.CharField(max_length=15, primary_key=True)
    
    nombre = models.CharField(max_length=100)

    class Meta:
        verbose_name = "Cuenta Principal"
        verbose_name_plural = "Cuentas Principales"
        ordering = ['codigo']

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

    # Método para obtener el saldo CONSOLIDADO de todas sus subcuentas
    def get_saldo_consolidado(self, tipo_registro_filtro=['NORMAL']):
        # Suma los saldos de TODAS las subcuentas relacionadas
        saldo_total = 0
        for subcuenta in self.subcuentas_set.all():
            saldo_total += subcuenta.get_saldo(tipo_registro_filtro)
        return saldo_total

# 2. SUBCUENTA (Modelo TRANSACCIONAL, donde se registran los movimientos)
class SubCuenta(models.Model):
    # La SubCuenta debe tener un código único
    codigo = models.CharField(max_length=30, unique=True, primary_key=True)
    
    # Relación 1:M con CuentaPrincipal. Indica a qué grupo pertenece.
    cuenta_principal = models.ForeignKey(
        CuentaPrincipal,
        on_delete=models.CASCADE,
        related_name='subcuentas_set', # Permite acceder a las subcuentas desde la principal (ej: principal.subcuentas_set.all())
        verbose_name='Cuenta de Agrupación'
    )
    
    nombre = models.CharField(max_length=100)

    class Meta:
        verbose_name = "Subcuenta Contable"
        verbose_name_plural = "Subcuentas Contables"
        ordering = ['codigo']

    def __str__(self):
        return f"{self.codigo} - {self.nombre} ({self.cuenta_principal.codigo})"

    # Método de cálculo para obtener el saldo (función dinámica, basada en sus propios movimientos)
    def get_saldo(self, tipo_registro_filtro=['NORMAL']):
        # Calcula la suma de todos los movimientos (Debe - Haber)
        # 'movimientos' es el related_name del FK en el modelo Movimiento que apunta a SubCuenta
        # NOTA Los movimientos de APERTURA siempre se incluyen automáticamente cuando se filtran movimientos por periodo
        debe = self.movimientos.filter(tipo_movimiento='Debe', tipo_registro__in=tipo_registro_filtro).aggregate(models.Sum('monto'))['monto__sum'] or 0
        haber = self.movimientos.filter(tipo_movimiento='Haber', tipo_registro__in=tipo_registro_filtro).aggregate(models.Sum('monto'))['monto__sum'] or 0
        return debe - haber

# 3. PERIODO CONTABLE 
class PeriodoContable(models.Model):
    nombre = models.CharField(max_length=100, unique=True, help_text="Ej: 'Enero 2025' o 'Año 2025'")
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(unique=True) # Solo una fecha de fin por período
    
    ESTADO_CHOICES = [
        ('ABIERTO', 'Abierto'),
        ('CERRADO', 'Cerrado'),
    ]
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='ABIERTO')

    class Meta:
        verbose_name = "Período Contable"
        verbose_name_plural = "Períodos Contables"
        ordering = ['-fecha_inicio'] # El más reciente primero

    def __str__(self):
        return f"{self.nombre} ({self.get_estado_display()})"


# 4. TRANSACCION 
class Transaccion(models.Model):
    
    periodo = models.ForeignKey(
        PeriodoContable, 
        on_delete=models.PROTECT, # No deja borrar un período si tiene transacciones
        related_name='transacciones',
        editable=False, # Hacemos que se asigne solo, en el guardado
        null=True # Temporalmente null=True para migraciones
    )
    
    fecha = models.DateField()
    descripcion = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Transacción Contable"
        verbose_name_plural = "Transacciones Contables"
        ordering = ['-fecha']

    def __str__(self):
        return f"T{self.pk}: {self.descripcion} ({self.fecha})"
        
    def validar_partida_doble(self):
        # ... (tu método de validación sigue igual) ...
        debe = self.movimientos.filter(tipo_movimiento='Debe').aggregate(models.Sum('monto'))['monto__sum'] or 0
        haber = self.movimientos.filter(tipo_movimiento='Haber').aggregate(models.Sum('monto'))['monto__sum'] or 0
        return debe == haber

  #Asignar período automáticamente al guardar
    def save(self, *args, **kwargs):
        # Si la transacción es nueva o la fecha cambió
        if not self.pk or 'fecha' in kwargs.get('update_fields', []):
            
            # Buscar un período ABIERTO que contenga esta fecha
            periodo_encontrado = PeriodoContable.objects.filter(
                fecha_inicio__lte=self.fecha,
                fecha_fin__gte=self.fecha,
                estado='ABIERTO'
            ).first()

            if not periodo_encontrado:
                # Si no hay período, no dejamos guardar la transacción
                raise ValidationError(
                    f"No existe un período contable Abierto para la fecha especificada"
                )
            
            self.periodo = periodo_encontrado

        super().save(*args, **kwargs) # Llama al método de guardado original


# 4. MOVIMIENTO
class Movimiento(models.Model):

    transaccion = models.ForeignKey(
        'Transaccion', 
        on_delete=models.CASCADE,
        related_name='movimientos'
    )
    
    subcuenta = models.ForeignKey(
        'SubCuenta',
        on_delete=models.PROTECT,
        related_name='movimientos'
    )

    TIPO_MOVIMIENTO_CHOICES = [
        ('Debe', 'Débito / Cargo'),
        ('Haber', 'Crédito / Abono'),
    ]
    tipo_movimiento = models.CharField(max_length=5, choices=TIPO_MOVIMIENTO_CHOICES)

    TIPO_REGISTRO_CHOICES = [
        ('NORMAL', 'Operación Diaria'),
        ('AJUSTE', 'Asiento de Ajuste (Depreciación, etc.)'),
        ('CIERRE', 'Asiento de Cierre de Cuentas Nominales'),
        ('APERTURA', 'Asiento de Apertura (Saldos Iniciales)'),
    ]
    tipo_registro = models.CharField(max_length=10, choices=TIPO_REGISTRO_CHOICES, default='NORMAL')

    monto = models.DecimalField(max_digits=15, decimal_places=2)
    
    class Meta:
        verbose_name = "Movimiento Contable"
        verbose_name_plural = "Movimientos Contables"
        ordering = ['transaccion__fecha'] 

    def __str__(self):
        return f"{self.tipo_movimiento} ${self.monto} en {self.subcuenta.codigo} (T{self.transaccion.pk})"
