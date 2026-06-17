from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.contrib import messages
from django.utils import timezone
from django import forms
from .models import Transaccion, Movimiento, SubCuenta, PeriodoContable, CuentaPrincipal
from .forms import TransaccionForm, MovimientoFormSet
from django.db.models import Sum, Q, F, Case, When, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from django.http import JsonResponse
from django.http import HttpResponse
import io
import csv
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import re

# Cuentas que DISPARAN el cálculo de IVA
APLICA_IVA_CODIGOS = {
    'P3',  # Ingresos DIFERIDOS por suscripciones SaaS
    'A4',  # Seguros Pagados por Adelantado
    'A5',  # Alquileres Pagados por Adelantado
    'A7',  # Equipos de cómputo
    'A8',  # Inmobiliario
    'G3',  # Servicios de nube (AWS, Azure)
    'G4',  # Publicidad y marketing digital
    'G5',  # Gastos administrativos
}

# Cuentas de IVA que se usarán para el cálculo
CUENTA_IVA_CREDITO = 'A3'
CUENTA_IVA_DEBITO = 'P4'
TASA_IVA = Decimal('0.13') # Usar Decimal para precisión financiera
COSTO_UNITARIO_SUSCRIPCION = Decimal('10.00')
CUENTA_COSTO_VENTA = 'G1'
CUENTA_INVENTARIO = 'A12'

def registrar_transaccion(request, tipo_valor):

    # Se lo usaremos en ambos casos (GET y POST)
    all_subcuentas = SubCuenta.objects.select_related('cuenta_principal').all().order_by('codigo')

    if request.method == 'POST':
        # --- Lógica del POST ---
        transaccion_form = TransaccionForm(request.POST)
        formset = MovimientoFormSet(request.POST)

        modo = request.POST.get('modo-transaccion')

        if transaccion_form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    # --- Lógica de guardado ---
                    transaccion_instance = transaccion_form.save(commit=False)
                    transaccion_instance.fecha = timezone.localtime().date()
                    
                    from django.core.exceptions import ValidationError as DjangoValidationError
                    periodo_encontrado = PeriodoContable.objects.filter(
                        fecha_inicio__lte=transaccion_instance.fecha,
                        fecha_fin__gte=transaccion_instance.fecha,
                        estado='ABIERTO'
                    ).first()
                    
                    if not periodo_encontrado:
                        mensaje_error = f'No se puede registrar la transacción: No existe un período contable ABIERTO que cubra la fecha {transaccion_instance.fecha.strftime("%d/%m/%Y")}. Por favor, vaya a "Libro Mayor" y cree un período contable que incluya la fecha actual.'
                        messages.error(request, mensaje_error)
                        raise forms.ValidationError("Periodo contable no disponible")
                    
                    transaccion_instance.save()
                    movimientos_a_guardar = formset.save(commit=False)

                    if modo == 'manual':
                        debe_total, haber_total, movimientos_validos = procesar_partida_manual(
                            movimientos_a_guardar, transaccion_instance, tipo_valor
                        )
                    elif modo in ('compra', 'venta'):
                        debe_total, haber_total, movimientos_validos = procesar_partida_automatica(
                            movimientos_a_guardar, transaccion_instance, tipo_valor, modo
                        )
                    else:
                        raise forms.ValidationError("Modo de transacción no válido.")

                    if abs(debe_total - haber_total) > Decimal('0.005'):
                        raise forms.ValidationError(
                            f"El asiento no cumple la Partida Doble. Debe: ${debe_total:.2f}, Haber: ${haber_total:.2f}."
                        )
                    if not movimientos_validos:
                        raise forms.ValidationError("Debe registrar al menos un movimiento válido.")

                    for movimiento in movimientos_validos:
                        movimiento.save()
                    for form in formset.deleted_forms:
                        if form.instance.pk:
                            form.instance.delete()
                    # --- Fin lógica de guardado ---

                    # ¡ÉXITO!
                    messages.success(request, f"Transacción T{transaccion_instance.pk} registrada con éxito. Total: ${debe_total:.2f}")
                    return redirect(request.path_info) # Redirige en éxito

            except forms.ValidationError as e:
                messages.error(request, f"Error de validación: {e.message if hasattr(e, 'message') else str(e)}")
            except DjangoValidationError as e:
                messages.error(request, f"Error de validación del modelo: {str(e)}")
            except Exception as e:
                messages.error(request, f"Error al guardar la transacción: {str(e)}")
        else: # (Esto es si is_valid() falla)
            messages.error(request, "Por favor, corrige los errores en los formularios.")

        # Si el POST falla (por error de validación o is_valid()=False),
        # llegamos aquí. Re-renderizamos la plantilla CON LOS MISMOS
        # FORMULARIOS LLENOS (bound forms) que recibimos.
        context = {
            'transaccion_form': transaccion_form, # El formulario LLENO
            'formset': formset,                 # El formset LLENO
            'all_subcuentas': all_subcuentas,
            'tipo_movimiento_choices': Movimiento.TIPO_MOVIMIENTO_CHOICES,
            'tipo_registro': tipo_valor
        }
        return render(request, 'registrarTransaccion.html', context)

    else:
        # --- Lógica del GET ---
        # (Este código ahora solo se ejecuta en GET)
        today = timezone.localtime().date()
        transaccion_form = TransaccionForm(initial={'fecha': today})
        formset = MovimientoFormSet(queryset=Movimiento.objects.none())

        context = {
            'transaccion_form': transaccion_form, # El formulario VACÍO
            'formset': formset,                 # El formset VACÍO
            'all_subcuentas': all_subcuentas,
            'tipo_movimiento_choices': Movimiento.TIPO_MOVIMIENTO_CHOICES,
            'tipo_registro': tipo_valor
        }
        return render(request, 'registrarTransaccion.html', context)

def procesar_partida_manual(movimientos_formset, transaccion, tipo_registro):
    debe_total = Decimal('0.0')
    haber_total = Decimal('0.0')
    movimientos_validos = []

    for movimiento in movimientos_formset:
        if not movimiento.monto:
            continue

        movimiento.transaccion = transaccion
        movimiento.tipo_registro = tipo_registro
        movimientos_validos.append(movimiento)

        if movimiento.tipo_movimiento == 'Debe':
            debe_total += movimiento.monto
        else:
            haber_total += movimiento.monto

    return debe_total, haber_total, movimientos_validos

def procesar_partida_automatica(movimientos_formset, transaccion, tipo_registro, modo):
    debe_total = Decimal('0.0')
    haber_total = Decimal('0.0')
    movimientos_validos = []

    if not movimientos_formset:
        raise forms.ValidationError("La transacción automática está vacía.")

    main_mov = movimientos_formset[0]
    main_mov.transaccion = transaccion
    main_mov.tipo_registro = tipo_registro
    main_monto = main_mov.monto

    if not main_monto:
        raise forms.ValidationError("El monto de la línea principal no puede ser cero.")

    if modo == 'compra':
        if main_mov.tipo_movimiento != 'Debe':
            raise forms.ValidationError(f"Error: La cuenta de Compra ({main_mov.subcuenta.codigo}) debe ir en el 'Debe'.")
        debe_total += main_monto
    else: # modo == 'venta'
        if main_mov.tipo_movimiento != 'Haber':
            raise forms.ValidationError(f"Error: La cuenta de Venta ({main_mov.subcuenta.codigo}) debe ir en el 'Haber'.")
        haber_total += main_monto

    movimientos_validos.append(main_mov)

    aplica_iva = main_mov.subcuenta.codigo in APLICA_IVA_CODIGOS

    if aplica_iva:
        if len(movimientos_formset) < 3:
            raise forms.ValidationError("Transacción incompleta. Faltan líneas de IVA o Pago.")

        iva_mov = movimientos_formset[1]
        iva_calculado_server = (main_monto * TASA_IVA).quantize(Decimal('0.01'))

        if iva_mov.monto != iva_calculado_server:
            raise forms.ValidationError(f"Cálculo de IVA incorrecto. El servidor esperaba ${iva_calculado_server} pero recibió ${iva_mov.monto}.")

        iva_mov.transaccion = transaccion
        iva_mov.tipo_registro = tipo_registro

        if modo == 'compra':
            if iva_mov.subcuenta.codigo != CUENTA_IVA_CREDITO or iva_mov.tipo_movimiento != 'Debe':
                raise forms.ValidationError(f"La línea de IVA debe ser {CUENTA_IVA_CREDITO} en el 'Debe'.")
            debe_total += iva_calculado_server
        else: # modo == 'venta'
            if iva_mov.subcuenta.codigo != CUENTA_IVA_DEBITO or iva_mov.tipo_movimiento != 'Haber':
                raise forms.ValidationError(f"La línea de IVA debe ser {CUENTA_IVA_DEBITO} en el 'Haber'.")
            haber_total += iva_calculado_server

        movimientos_validos.append(iva_mov)
        pago_mov = movimientos_formset[2]
        pago_total_calculado = main_monto + iva_calculado_server

    else:
        if len(movimientos_formset) < 2:
            raise forms.ValidationError("Transacción incompleta. Falta la línea de Pago.")

        pago_mov = movimientos_formset[1]
        pago_total_calculado = main_monto

    if pago_mov.monto != pago_total_calculado:
        raise forms.ValidationError(f"Cálculo del Total/Pago incorrecto. El servidor esperaba ${pago_total_calculado} pero recibió ${pago_mov.monto}.")

    pago_mov.transaccion = transaccion
    pago_mov.tipo_registro = tipo_registro

    if modo == 'compra':
        if pago_mov.tipo_movimiento != 'Haber':
            raise forms.ValidationError("La línea de Pago debe ir en el 'Haber'.")
        haber_total += pago_total_calculado
    else: # modo == 'venta'
        if pago_mov.tipo_movimiento != 'Debe':
            raise forms.ValidationError("La línea de Cobro debe ir en el 'Debe'.")
        debe_total += pago_total_calculado

    movimientos_validos.append(pago_mov)
    return debe_total, haber_total, movimientos_validos

def check_cuenta_iva_api(request):
    codigo_cuenta = request.GET.get('codigo')

    if not codigo_cuenta:
        return JsonResponse({'error': 'No se proporcionó código'}, status=400)

    # Comprobamos si el código está en set hard-codeado
    aplica = codigo_cuenta in APLICA_IVA_CODIGOS

    return JsonResponse({
        'codigo': codigo_cuenta,
        'aplica_iva': aplica
    })

def balance_comprobacion_ajustado(request):

    # 1. Obtener todos los períodos para el combobox
    todos_los_periodos = PeriodoContable.objects.all()

    # 2. Determinar qué período mostrar
    periodo_seleccionado = None
    periodo_id_query = request.GET.get('periodo_id') # Buscar en la URL

    if not todos_los_periodos.exists():
        # Caso 1: No hay períodos creados.
        pass
    elif periodo_id_query:
        # Caso 2: El usuario seleccionó un período específico
        try:
            periodo_seleccionado = todos_los_periodos.get(pk=periodo_id_query)
        except PeriodoContable.DoesNotExist:
            # Caso 3: El ID de la URL es inválido, cargamos el default
            periodo_seleccionado = todos_los_periodos.first()
    else:
        # Caso 4: Carga inicial de la página, cargamos el default
        periodo_seleccionado = todos_los_periodos.first() # .first() da el más reciente

    # --- Variables para el reporte ---
    reporte_data = SubCuenta.objects.none() # Queryset vacío por defecto
    total_debe = Decimal('0.00')
    total_haber = Decimal('0.00')
    balance_cuadrado = False

    # 5. Si SÍ tenemos un período, ejecutamos la lógica del reporte
    if periodo_seleccionado:
        fecha_inicio = periodo_seleccionado.fecha_inicio 
        fecha_corte = periodo_seleccionado.fecha_fin
        tipos_filtro = ['NORMAL', 'AJUSTE', 'APERTURA']

        monto_debe_ajustado = Coalesce(
            Sum('movimientos__monto',
                filter=Q(movimientos__tipo_movimiento='Debe',
                         movimientos__tipo_registro__in=tipos_filtro,
                          movimientos__transaccion__fecha__gte=fecha_inicio,
                         movimientos__transaccion__fecha__lte=fecha_corte)),
            Decimal('0.00'), output_field=DecimalField()
        )

        monto_haber_ajustado = Coalesce(
            Sum('movimientos__monto',
                filter=Q(movimientos__tipo_movimiento='Haber',
                         movimientos__tipo_registro__in=tipos_filtro,
                         movimientos__transaccion__fecha__gte=fecha_inicio,
                         movimientos__transaccion__fecha__lte=fecha_corte)),
            Decimal('0.00'), output_field=DecimalField()
        )

        subcuentas_con_saldos = SubCuenta.objects.annotate(
            saldo_neto=monto_debe_ajustado - monto_haber_ajustado
        )

        reporte_data = subcuentas_con_saldos.annotate(
            debe=Case(
                When(saldo_neto__gt=0, then=F('saldo_neto')),
                default=Decimal('0.00'), output_field=DecimalField()
            ),
            haber=Case(
                When(saldo_neto__lt=0, then=-F('saldo_neto')),
                default=Decimal('0.00'), output_field=DecimalField()
            )
        ).filter(Q(debe__gt=0) | Q(haber__gt=0)).order_by('codigo')

        totales = reporte_data.aggregate(
            total_debe=Sum('debe'),
            total_haber=Sum('haber')
        )

        total_debe = totales.get('total_debe') or Decimal('0.00')
        total_haber = totales.get('total_haber') or Decimal('0.00')
        balance_cuadrado = (total_debe == total_haber)

    # 6. Preparamos el contexto
    context = {
        'todos_los_periodos': todos_los_periodos,   # Para el combobox
        'periodo_seleccionado': periodo_seleccionado, # Para el título y el 'selected'
        'lineas': reporte_data,                 # Los datos de la tabla
        'total_debe': total_debe,
        'total_haber': total_haber,
        'balance_cuadrado': balance_cuadrado,
    }

    return render(request, 'balanceComprobacionAjustado.html', context)

def home(request):
    return render(request, 'home.html')

def hoja_trabajo(request):
    return render(request, 'hojaTrabajo.html')

def catalogo(request):
    
    def ordenar_codigo_numerico(codigo):
        match = re.match(r'^([A-Za-z]+)(\d+)$', str(codigo))
        if match:
            letra = match.group(1)
            numero = int(match.group(2))
            return (letra, numero)
        return (codigo, 0)
    
    cuentas_principales = CuentaPrincipal.objects.prefetch_related('subcuentas_set').all().order_by('codigo')

    activos = []
    pasivos = []
    patrimonio = []

    ingresos = []
    gastos = []

    for cp in cuentas_principales:
        codigo = cp.codigo.upper() if cp.codigo else ''
        subcuentas_ordenadas = sorted(cp.subcuentas_set.all(), key=lambda x: ordenar_codigo_numerico(x.codigo))
        cuenta_data = {
            'cuenta_principal': cp,
            'subcuentas': subcuentas_ordenadas
        }

        if codigo == 'A' or codigo.startswith('A'):
            activos.append(cuenta_data)
        elif codigo == 'P' or codigo.startswith('P'):
            pasivos.append(cuenta_data)
        elif codigo == 'C' or codigo.startswith('C'):
            patrimonio.append(cuenta_data)
        elif codigo == 'I' or codigo.startswith('I'):
            ingresos.append(cuenta_data)
        elif codigo == 'G' or codigo.startswith('G'):
            gastos.append(cuenta_data)

    context = {
        'activos': activos,
        'pasivos': pasivos,
        'patrimonio': patrimonio,
        'ingresos': ingresos,
        'gastos': gastos,
    }

    return render(request, 'catalogo.html', context)

def estado_capital(request):
     periodos_cerrados = PeriodoContable.objects.filter(estado="CERRADO").order_by(
         "-fecha_inicio"
     )
     sin_periodos_cerrados = not periodos_cerrados.exists()

     periodo_seleccionado = None
     periodo_id = request.GET.get("periodo_id")

     if not sin_periodos_cerrados:
         if periodo_id:
             try:
                 periodo_seleccionado = periodos_cerrados.get(pk=periodo_id)
             except PeriodoContable.DoesNotExist:
                 periodo_seleccionado = periodos_cerrados.first()
         else:
             periodo_seleccionado = periodos_cerrados.first()

     try:
         cuenta_capital = CuentaPrincipal.objects.get(codigo="C")
     except CuentaPrincipal.DoesNotExist:
         cuenta_capital = None

     try:
         cuenta_ingresos = CuentaPrincipal.objects.get(codigo="I")
     except CuentaPrincipal.DoesNotExist:
         cuenta_ingresos = None

     try:
         cuenta_gastos = CuentaPrincipal.objects.get(codigo="G")
     except CuentaPrincipal.DoesNotExist:
         cuenta_gastos = None

     subcuentas_capital = []
     total_patrimonio = Decimal("0.00")
     total_ingresos = Decimal("0.00")
     total_gastos = Decimal("0.00")
     resultado_neto = Decimal("0.00")
     resultado_neto_abs = Decimal("0.00")

     if cuenta_capital and periodo_seleccionado:
         subcuentas = SubCuenta.objects.filter(cuenta_principal=cuenta_capital).order_by(
             "codigo"
         )

         for subcuenta in subcuentas:
             debe = subcuenta.movimientos.filter(
                 tipo_movimiento="Debe", transaccion__periodo=periodo_seleccionado
             ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

             haber = subcuenta.movimientos.filter(
                 tipo_movimiento="Haber", transaccion__periodo=periodo_seleccionado
             ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

             saldo = debe - haber

             if saldo != 0:
                 subcuentas_capital.append(
                     {
                         "codigo": subcuenta.codigo,
                         "nombre": subcuenta.nombre,
                         "saldo": saldo,
                     }
                 )
                 total_patrimonio += saldo

     if cuenta_ingresos and periodo_seleccionado:
         subcuentas = SubCuenta.objects.filter(
             cuenta_principal=cuenta_ingresos
         ).order_by("codigo")

         for subcuenta in subcuentas:
             debe = subcuenta.movimientos.filter(
                 tipo_movimiento="Debe", transaccion__periodo=periodo_seleccionado
             ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

             haber = subcuenta.movimientos.filter(
                 tipo_movimiento="Haber", transaccion__periodo=periodo_seleccionado
             ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

             saldo = haber - debe
             total_ingresos += saldo

     if cuenta_gastos and periodo_seleccionado:
         subcuentas = SubCuenta.objects.filter(cuenta_principal=cuenta_gastos).order_by(
             "codigo"
         )

         for subcuenta in subcuentas:
             debe = subcuenta.movimientos.filter(
                 tipo_movimiento="Debe", transaccion__periodo=periodo_seleccionado
             ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

             haber = subcuenta.movimientos.filter(
                 tipo_movimiento="Haber", transaccion__periodo=periodo_seleccionado
             ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

             saldo = debe - haber
             total_gastos += saldo

     resultado_neto = total_ingresos - total_gastos
     resultado_neto_abs = abs(resultado_neto)
     
     total_patrimonio_con_utilidad = abs(total_patrimonio) + resultado_neto
     total_patrimonio_con_utilidad_abs = abs(total_patrimonio_con_utilidad)

     context = {
         "periodos_cerrados": periodos_cerrados,
         "periodo_seleccionado": periodo_seleccionado,
         "sin_periodos_cerrados": sin_periodos_cerrados,
         "subcuentas_capital": subcuentas_capital,
         "total_patrimonio": total_patrimonio,
         "total_ingresos": total_ingresos,
         "total_gastos": total_gastos,
         "resultado_neto": resultado_neto,
         "resultado_neto_abs": resultado_neto_abs,
         "total_patrimonio_con_utilidad": total_patrimonio_con_utilidad,
        "total_patrimonio_con_utilidad_abs": total_patrimonio_con_utilidad_abs,
     }

     return render(request, "estadoCapital.html", context)

def estado_resultado(request):
    periodos_cerrados = PeriodoContable.objects.filter(estado="CERRADO").order_by(
        "-fecha_inicio"
    )
    sin_periodos_cerrados = not periodos_cerrados.exists()

    periodo_seleccionado = None
    periodo_id = request.GET.get("periodo_id")

    if not sin_periodos_cerrados:
        if periodo_id:
            try:
                periodo_seleccionado = periodos_cerrados.get(pk=periodo_id)
            except PeriodoContable.DoesNotExist:
                periodo_seleccionado = periodos_cerrados.first()
        else:
            periodo_seleccionado = periodos_cerrados.first()

    try:
        cuenta_ingresos = CuentaPrincipal.objects.get(codigo="I")
    except CuentaPrincipal.DoesNotExist:
        cuenta_ingresos = None

    try:
        cuenta_gastos = CuentaPrincipal.objects.get(codigo="G")
    except CuentaPrincipal.DoesNotExist:
        cuenta_gastos = None

    subcuentas_ingresos = []
    total_ingresos = Decimal("0.00")

    if cuenta_ingresos and periodo_seleccionado:
        subcuentas = SubCuenta.objects.filter(
            cuenta_principal=cuenta_ingresos
        ).order_by("codigo")

        for subcuenta in subcuentas:
            debe = subcuenta.movimientos.filter(
                tipo_movimiento="Debe", transaccion__periodo=periodo_seleccionado
            ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

            haber = subcuenta.movimientos.filter(
                tipo_movimiento="Haber", transaccion__periodo=periodo_seleccionado
            ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

            saldo = haber - debe

            if saldo != 0:
                subcuentas_ingresos.append(
                    {
                        "codigo": subcuenta.codigo,
                        "nombre": subcuenta.nombre,
                        "saldo": saldo,
                    }
                )
                total_ingresos += saldo

    subcuentas_gastos = []
    total_gastos = Decimal("0.00")

    if cuenta_gastos and periodo_seleccionado:
        subcuentas = SubCuenta.objects.filter(cuenta_principal=cuenta_gastos).order_by(
            "codigo"
        )

        for subcuenta in subcuentas:
            debe = subcuenta.movimientos.filter(
                tipo_movimiento="Debe", transaccion__periodo=periodo_seleccionado
            ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

            haber = subcuenta.movimientos.filter(
                tipo_movimiento="Haber", transaccion__periodo=periodo_seleccionado
            ).aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

            saldo = debe - haber

            if saldo != 0:
                subcuentas_gastos.append(
                    {
                        "codigo": subcuenta.codigo,
                        "nombre": subcuenta.nombre,
                        "saldo": saldo,
                    }
                )
                total_gastos += saldo

    resultado_neto = total_ingresos - total_gastos
    resultado_neto_abs = abs(resultado_neto)

    context = {
        "periodos_cerrados": periodos_cerrados,
        "periodo_seleccionado": periodo_seleccionado,
        "sin_periodos_cerrados": sin_periodos_cerrados,
        "subcuentas_ingresos": subcuentas_ingresos,
        "subcuentas_gastos": subcuentas_gastos,
        "total_ingresos": total_ingresos,
        "total_gastos": total_gastos,
        "resultado_neto": resultado_neto,
        "resultado_neto_abs": resultado_neto_abs,
    }

    return render(request, "estadoResultado.html", context)

def costos(request):
    return render(request, 'costos.html')

def libro_mayor(request):
    todos_periodos = PeriodoContable.objects.all().order_by('-fecha_inicio')
    periodo_activo = PeriodoContable.objects.filter(estado='ABIERTO').first()
    
    ultimo_periodo_cerrado = PeriodoContable.objects.filter(estado='CERRADO').order_by('-fecha_fin').first()
    fecha_minima_permitida = None
    
    if ultimo_periodo_cerrado:
        from datetime import timedelta
        fecha_minima_permitida = ultimo_periodo_cerrado.fecha_fin + timedelta(days=1)
    
    fecha_hoy = timezone.now().date()
    periodo_cubre_hoy = False
    
    if periodo_activo:
        if periodo_activo.fecha_inicio <= fecha_hoy <= periodo_activo.fecha_fin:
            periodo_cubre_hoy = True
        else:
            messages.warning(
                request, 
                f'El período activo "{periodo_activo.nombre}" ({periodo_activo.fecha_inicio.strftime("%d/%m/%Y")} - {periodo_activo.fecha_fin.strftime("%d/%m/%Y")}) '
                f'NO cubre la fecha actual ({fecha_hoy.strftime("%d/%m/%Y")}). '
                f'No podrá registrar transacciones hasta cerrar este período y crear uno nuevo que incluya la fecha actual.'
            )
    else:
        messages.warning(
            request,
            'No hay ningún período contable abierto. Debe crear un período que incluya la fecha actual para poder registrar transacciones.'
        )
    
    periodo_id = request.GET.get('periodo')
    periodo_seleccionado = None
    
    if periodo_id:
        try:
            periodo_seleccionado = PeriodoContable.objects.get(pk=periodo_id)
        except PeriodoContable.DoesNotExist:
            periodo_seleccionado = periodo_activo
    else:
        periodo_seleccionado = periodo_activo
    
    cuentas_principales = (
        CuentaPrincipal.objects.prefetch_related("subcuentas_set")
        .all()
        .order_by("codigo")
    )

    categorias = {
        "A": {"nombre": "Activos", "cuentas": []},
        "P": {"nombre": "Pasivos", "cuentas": []},
        "C": {"nombre": "Capital", "cuentas": []},
        "I": {"nombre": "Ingresos", "cuentas": []},
        "G": {"nombre": "Gastos y Costos", "cuentas": []},
    }

    for cp in cuentas_principales:
        codigo = cp.codigo.upper() if cp.codigo else ""

        subcuentas = SubCuenta.objects.filter(cuenta_principal=cp).order_by("codigo")

        for subcuenta in subcuentas:
            movimientos_query = Movimiento.objects.filter(subcuenta=subcuenta).select_related("transaccion")
            
            if periodo_seleccionado:
                movimientos_query = movimientos_query.filter(transaccion__periodo=periodo_seleccionado)
            
            movimientos = movimientos_query.order_by("transaccion__fecha", "id")

            if not movimientos.exists():
                continue

            debe_total = movimientos.filter(tipo_movimiento="Debe").aggregate(
                total=Sum("monto")
            )["total"] or Decimal("0.00")

            haber_total = movimientos.filter(tipo_movimiento="Haber").aggregate(
                total=Sum("monto")
            )["total"] or Decimal("0.00")

            saldo = abs(debe_total - haber_total)

            movimientos_list = []
            for mov in movimientos:
                movimientos_list.append(
                    {
                        "fecha": mov.transaccion.fecha,
                        "descripcion": mov.transaccion.descripcion,
                        "tipo": mov.tipo_movimiento,
                        "monto": mov.monto,
                        "tipo_registro": mov.tipo_registro,
                    }
                )

            cuenta_data = {
                "codigo": subcuenta.codigo,
                "nombre": subcuenta.nombre,
                "movimientos": movimientos_list,
                "debe_total": debe_total,
                "haber_total": haber_total,
                "saldo": saldo,
            }

            if codigo.startswith("A"):
                categorias["A"]["cuentas"].append(cuenta_data)
            elif codigo.startswith("P"):
                categorias["P"]["cuentas"].append(cuenta_data)
            elif codigo.startswith("C"):
                categorias["C"]["cuentas"].append(cuenta_data)
            elif codigo.startswith("I"):
                categorias["I"]["cuentas"].append(cuenta_data)
            elif codigo.startswith("G"):
                categorias["G"]["cuentas"].append(cuenta_data)
    
    context = {
        "categorias": categorias,
        "periodo_activo": periodo_activo,
        "hay_periodo_abierto": periodo_activo is not None,
        "todos_periodos": todos_periodos,
        "periodo_seleccionado": periodo_seleccionado,
        "fecha_minima_permitida": fecha_minima_permitida,
        "ultimo_periodo_cerrado": ultimo_periodo_cerrado,
    }

    return render(request, "libroMayor.html", context)


def crear_asiento_apertura(nuevo_periodo, periodo_anterior, fecha_apertura):
    # 1. Obtener saldos de cuentas de balance (A, P, C)
    subcuentas_balance = SubCuenta.objects.filter(
        cuenta_principal__codigo__in=['A', 'P', 'C']
    ).select_related('cuenta_principal')
    
    saldos_apertura = []
    
    for subcuenta in subcuentas_balance:
        debe = subcuenta.movimientos.filter(
            tipo_movimiento='Debe',
            transaccion__periodo=periodo_anterior
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        haber = subcuenta.movimientos.filter(
            tipo_movimiento='Haber',
            transaccion__periodo=periodo_anterior
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        saldo_neto = debe - haber
        if saldo_neto > 0:
            saldos_apertura.append({
                'subcuenta': subcuenta,
                'tipo_movimiento': 'Debe',
                'monto': saldo_neto
            })
        elif saldo_neto < 0:
            saldos_apertura.append({
                'subcuenta': subcuenta,
                'tipo_movimiento': 'Haber',
                'monto': abs(saldo_neto)
            })
    
    subcuentas_ingresos = SubCuenta.objects.filter(
        cuenta_principal__codigo='I'
    )
    total_ingresos = Decimal('0.00')
    for subcuenta in subcuentas_ingresos:
        debe = subcuenta.movimientos.filter(
            tipo_movimiento='Debe',
            transaccion__periodo=periodo_anterior
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        haber = subcuenta.movimientos.filter(
            tipo_movimiento='Haber',
            transaccion__periodo=periodo_anterior
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        total_ingresos += (haber - debe)
    
    subcuentas_gastos = SubCuenta.objects.filter(
        cuenta_principal__codigo='G'
    )
    total_gastos = Decimal('0.00')
    for subcuenta in subcuentas_gastos:
        debe = subcuenta.movimientos.filter(
            tipo_movimiento='Debe',
            transaccion__periodo=periodo_anterior
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        haber = subcuenta.movimientos.filter(
            tipo_movimiento='Haber',
            transaccion__periodo=periodo_anterior
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        total_gastos += (debe - haber)
    
    utilidad_ejercicio = total_ingresos - total_gastos
    
    if utilidad_ejercicio != Decimal('0.00'):
        try:
            cuenta_utilidad = SubCuenta.objects.get(codigo='C2')
        except SubCuenta.DoesNotExist:
            try:
                cuenta_principal_c = CuentaPrincipal.objects.get(codigo='C')
            except CuentaPrincipal.DoesNotExist:
                cuenta_principal_c = CuentaPrincipal.objects.create(
                    codigo='C',
                    nombre='Capital y Patrimonio'
                )
            
            cuenta_utilidad = SubCuenta.objects.create(
                codigo='C2',
                nombre='Utilidad del Ejercicio',
                cuenta_principal=cuenta_principal_c
            )
        
        if utilidad_ejercicio > 0:
            saldos_apertura.append({
                'subcuenta': cuenta_utilidad,
                'tipo_movimiento': 'Haber',
                'monto': utilidad_ejercicio
            })
        else:
            saldos_apertura.append({
                'subcuenta': cuenta_utilidad,
                'tipo_movimiento': 'Debe',
                'monto': abs(utilidad_ejercicio)
            })
    
    if saldos_apertura:
        transaccion_apertura = Transaccion.objects.create(
            periodo=nuevo_periodo,
            fecha=fecha_apertura,
            descripcion=f'Asiento de Apertura - Saldos iniciales del periodo {periodo_anterior.nombre}'
        )
        for saldo_data in saldos_apertura:
            Movimiento.objects.create(
                transaccion=transaccion_apertura,
                subcuenta=saldo_data['subcuenta'],
                tipo_movimiento=saldo_data['tipo_movimiento'],
                monto=saldo_data['monto'],
                tipo_registro='APERTURA'
            )
        
        return transaccion_apertura
    
    return None


def cerrar_periodo_contable(request):
    if request.method == 'POST':
        periodo_activo = PeriodoContable.objects.filter(estado='ABIERTO').first()
        
        if not periodo_activo:
            messages.error(request, 'No hay ningún período contable abierto para cerrar.')
            return redirect('libro_mayor')
        
        periodo_activo.estado = 'CERRADO'
        periodo_activo.save()
        
        messages.success(request, f'Período contable "{periodo_activo.nombre}" ha sido cerrado exitosamente.')
        return redirect('libro_mayor')
    
    return redirect('libro_mayor')


def crear_periodo_contable(request):
    if request.method == 'POST':
        periodo_abierto = PeriodoContable.objects.filter(estado='ABIERTO').first()
        
        if periodo_abierto:
            messages.error(request, 'No se puede crear un nuevo período contable mientras hay uno abierto. Cierre el período actual primero.')
            return redirect('libro_mayor')
        
        nombre = request.POST.get('nombre')
        fecha_inicio_input = request.POST.get('fecha_inicio')
        fecha_fin = request.POST.get('fecha_fin')
        
        if not nombre or not fecha_inicio_input or not fecha_fin:
            messages.error(request, 'Debe proporcionar un nombre, fecha de inicio y fecha de fin para el período.')
            return redirect('libro_mayor')
        
        try:
            from datetime import datetime, timedelta
            fecha_inicio = datetime.strptime(fecha_inicio_input, '%Y-%m-%d').date()
            fecha_fin_obj = datetime.strptime(fecha_fin, '%Y-%m-%d').date()
            
            ultimo_periodo_cerrado = PeriodoContable.objects.filter(estado='CERRADO').order_by('-fecha_fin').first()
            fecha_hoy = datetime.now().date()
            
            if ultimo_periodo_cerrado:
                fecha_minima = ultimo_periodo_cerrado.fecha_fin + timedelta(days=1)
                if fecha_inicio < fecha_minima:
                    messages.error(
                        request, 
                        f'La fecha de inicio ({fecha_inicio.strftime("%d/%m/%Y")}) no puede ser anterior al día siguiente del último período cerrado ({fecha_minima.strftime("%d/%m/%Y")}).'
                    )
                    return redirect('libro_mayor')
            else:
                # Si no hay ningún periodo cerrado (primer periodo), la fecha de inicio no puede ser anterior a hoy
                if fecha_inicio < fecha_hoy:
                    messages.error(
                        request,
                        f'La fecha de inicio ({fecha_inicio.strftime("%d/%m/%Y")}) no puede ser anterior a la fecha actual ({fecha_hoy.strftime("%d/%m/%Y")}) al crear el primer período contable.'
                    )
                    return redirect('libro_mayor')
            
            if fecha_fin_obj < fecha_inicio:
                messages.error(request, 'La fecha de fin no puede ser anterior a la fecha de inicio (hoy).')
                return redirect('libro_mayor')
            
            if PeriodoContable.objects.filter(nombre=nombre).exists():
                messages.error(request, f'Ya existe un período contable con el nombre "{nombre}". Use otro nombre.')
                return redirect('libro_mayor')
            
            if PeriodoContable.objects.filter(fecha_fin=fecha_fin_obj).exists():
                messages.error(request, f'Ya existe un período contable con la fecha de fin {fecha_fin_obj.strftime("%d/%m/%Y")}. Use otra fecha.')
                return redirect('libro_mayor')
            
            with transaction.atomic():
                nuevo_periodo = PeriodoContable.objects.create(
                    nombre=nombre,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin_obj,
                    estado='ABIERTO'
                )
                
                if ultimo_periodo_cerrado:
                    crear_asiento_apertura(nuevo_periodo, ultimo_periodo_cerrado, fecha_inicio)
                    mensaje_exito = f'Período contable "{nuevo_periodo.nombre}" creado exitosamente con saldos iniciales del periodo anterior. Rango: {fecha_inicio.strftime("%d/%m/%Y")} - {fecha_fin_obj.strftime("%d/%m/%Y")}.'
                else:
                    mensaje_exito = f'Período contable "{nuevo_periodo.nombre}" creado exitosamente. Rango: {fecha_inicio.strftime("%d/%m/%Y")} - {fecha_fin_obj.strftime("%d/%m/%Y")}. Ahora puede registrar transacciones dentro de este período.'
                
                messages.success(request, mensaje_exito)
            
            return redirect('libro_mayor')
            
        except ValueError as e:
            messages.error(request, f'Formato de fecha inválido: {str(e)}')
            return redirect('libro_mayor')
        except Exception as e:
            messages.error(request, f'Error al crear el período: {str(e)}')
            return redirect('libro_mayor')
    
    return redirect('libro_mayor')

def balanceComprobacion(request):
    return render(request, 'balanceComprobacion.html')

def balanceComprobacion(request):    # Lista de periodos para el select
    # Obtener solo períodos ABIERTO, ordenados del más reciente al más antiguo
    periodos = PeriodoContable.objects.filter(estado='ABIERTO').order_by('-fecha_inicio')

    # Indica si existen periodos contables abiertos (usado para mostrar mensaje en la plantilla)
    hay_periodos_abiertos = periodos.exists()

    periodo_obj = None
    periodo_pk = request.GET.get('periodo')
    if periodo_pk:
        # Si el usuario envía un periodo por GET, intentar cargarlo (puede ser abierto o cerrado)
        try:
            periodo_obj = PeriodoContable.objects.get(pk=periodo_pk)
        except PeriodoContable.DoesNotExist:
            periodo_obj = None
    else:
        # Si no se especifica, elegir por defecto el periodo ABIERTO más reciente (si existe)
        if periodos.exists():
            periodo_obj = periodos.first()

    # Preparar queryset de subcuentas con anotaciones de debe/haber para el periodo seleccionado
    subcuentas = SubCuenta.objects.all().order_by('codigo')

    # En la parte donde se calcula debe_ann y haber_ann, agregar el filtro por tipo_registro:

# Definir filtro para movimientos NORMALES y de APERTURA
    filtro_tipos = Q(movimientos__tipo_registro='NORMAL') | Q(movimientos__tipo_registro='APERTURA')

    if periodo_obj:
        # Combinar filtro de tipos con filtro de periodo
        filtro_debe = filtro_tipos & Q(movimientos__tipo_movimiento='Debe', movimientos__transaccion__periodo=periodo_obj)
        filtro_haber = filtro_tipos & Q(movimientos__tipo_movimiento='Haber', movimientos__transaccion__periodo=periodo_obj)

        debe_ann = Coalesce(Sum('movimientos__monto', filter=filtro_debe), Decimal('0.00'))
        haber_ann = Coalesce(Sum('movimientos__monto', filter=filtro_haber), Decimal('0.00'))

        subcuentas = subcuentas.annotate(debe=debe_ann, haber=haber_ann)
    else:
        # Sin periodo, solo filtro de tipos
        filtro_debe = filtro_tipos & Q(movimientos__tipo_movimiento='Debe')
        filtro_haber = filtro_tipos & Q(movimientos__tipo_movimiento='Haber')

        subcuentas = subcuentas.annotate(
            debe=Coalesce(Sum('movimientos__monto', filter=filtro_debe), Decimal('0.00')),
            haber=Coalesce(Sum('movimientos__monto', filter=filtro_haber), Decimal('0.00')),
        )

    # Calcular el SALDO NETO de cada subcuenta y presentarlo como saldo final
    subcuentas = subcuentas.annotate(
        saldo_neto=F('debe') - F('haber')
    ).annotate(
        debe_final=Case(
            When(saldo_neto__gt=0, then=F('saldo_neto')),
            default=Decimal('0.00'), output_field=DecimalField()
        ),
        haber_final=Case(
            When(saldo_neto__lt=0, then=-F('saldo_neto')),
            default=Decimal('0.00'), output_field=DecimalField()
        )
    ).filter(Q(debe_final__gt=0) | Q(haber_final__gt=0)).order_by('codigo')

    # Calcular totales a partir de los saldos finales (saldos de las cuentas)
    totales = subcuentas.aggregate(
        total_debe=Coalesce(Sum('debe_final'), Decimal('0.00'), output_field=DecimalField()),
        total_haber=Coalesce(Sum('haber_final'), Decimal('0.00'), output_field=DecimalField())
    )

    total_debe = totales.get('total_debe') or Decimal('0.00')
    total_haber = totales.get('total_haber') or Decimal('0.00')

    context = {
        # 'periodos' ahora contiene únicamente los periodos ABIERTO (posiblemente vacío)
        'periodos': periodos,
        'periodo': periodo_obj,
        'subcuentas': subcuentas,
        'total_debe': total_debe,
        'total_haber': total_haber,
        'hay_periodos_abiertos': hay_periodos_abiertos,
    }

    # Exporta el CSV de la tabla si se solicita
    if request.GET.get('export') == 'csv':
        # Create CSV in memory
        buf = io.StringIO()
        writer = csv.writer(buf)
        # Cabecera
        writer.writerow(['Cuenta', 'Debe', 'Haber'])
        for s in subcuentas:
            cuenta_label = f"{getattr(s, 'cuenta_principal', None) and s.cuenta_principal.codigo or ''} - {s.nombre}"
            debe = (getattr(s, 'debe_final', None) or 0)
            haber = (getattr(s, 'haber_final', None) or 0)
            writer.writerow([cuenta_label, f"{debe:.2f}", f"{haber:.2f}"])

        # Fila de totales
        writer.writerow(['Totales', f"{total_debe:.2f}", f"{total_haber:.2f}"])

        resp = HttpResponse(buf.getvalue(), content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename="balance_periodo.csv"'
        return resp

    return render(request, 'balanceComprobacion.html', context)


def balance_general_cerrado(request):
    """Vista para renderizar la plantilla `balance_general_cerrado.html` usando
    datos reales de los modelos. Agrupa por subcuentas y clasifica cada subcuenta
    en Activos / Pasivos / Patrimonio usando la misma heurística que
    `balanceGeneral`.
    """
    # 1. lista de periodos para filtro: sólo períodos CERRADO
    periodos = PeriodoContable.objects.filter(estado='CERRADO').order_by('-fecha_inicio')
    hay_periodos_cerrados = periodos.exists()
    periodo = None
    # Permitir seleccionar múltiples periodos: ?periodo=1&periodo=2
    periodo_pks = request.GET.getlist('periodo')
    selected_periods_qs = None
    # Sanitizar lista: eliminar valores vacíos (ocurre cuando el usuario vuelve a la opción por defecto "")
    periodo_pks = [p for p in periodo_pks if p and str(p).strip()]
    # Mostrar datos solo si el usuario envió explícitamente al menos un 'periodo' válido
    mostrar_datos = bool(periodo_pks)
    if periodo_pks:
        # Filtramos sólo los períodos cerrados entre los seleccionados
        selected_periods_qs = periodos.filter(pk__in=periodo_pks)
        periodo = selected_periods_qs.first() if selected_periods_qs.exists() else None
    else:
        if periodos.exists():
            periodo = periodos.first()

    # 2. Anotar cada SubCuenta con debe/haber (filtrando por transaccion.periodo si aplicable)
    # Construir filtros según si se seleccionaron múltiples periodos o uno sólo
    if selected_periods_qs is not None and selected_periods_qs.exists():
        debe_filter = Q(movimientos__tipo_movimiento='Debe', movimientos__transaccion__periodo__in=selected_periods_qs)
        haber_filter = Q(movimientos__tipo_movimiento='Haber', movimientos__transaccion__periodo__in=selected_periods_qs)
    elif periodo:
        debe_filter = Q(movimientos__tipo_movimiento='Debe', movimientos__transaccion__periodo=periodo)
        haber_filter = Q(movimientos__tipo_movimiento='Haber', movimientos__transaccion__periodo=periodo)
    else:
        debe_filter = Q(movimientos__tipo_movimiento='Debe')
        haber_filter = Q(movimientos__tipo_movimiento='Haber')

    subcuentas_qs = SubCuenta.objects.annotate(
        debe=Coalesce(Sum('movimientos__monto', filter=debe_filter), Decimal('0.00'), output_field=DecimalField()),
        haber=Coalesce(Sum('movimientos__monto', filter=haber_filter), Decimal('0.00'), output_field=DecimalField()),
    ).order_by('codigo')

    activos = []
    pasivos = []
    patrimonio = []

    total_activos = Decimal('0.00')
    total_pasivos = Decimal('0.00')
    total_patrimonio = Decimal('0.00')
    ingresos_total = Decimal('0.00')
    gastos_total = Decimal('0.00')

    for s in subcuentas_qs:
        cp = s.cuenta_principal
        codigo_cp = getattr(cp, 'codigo', '') or ''

        # Determinar naturaleza usando campo 'tipo' si existe, si no por prefijo
        tipo_cp = getattr(cp, 'tipo', None)
        naturaleza = None
        if isinstance(tipo_cp, str):
            tipo_norm = tipo_cp.strip().upper()
            if tipo_norm in ('ACTIVO', 'ACTIVOS'):
                naturaleza = 'ACTIVO'
            elif tipo_norm in ('PASIVO', 'PASIVOS'):
                naturaleza = 'PASIVO'
            elif tipo_norm in ('PATRIMONIO', 'CAPITAL', 'PATRIMONIOS'):
                naturaleza = 'PATRIMONIO'

        if not naturaleza:
            # Primero intentar por letra (convención del catálogo)
            if codigo_cp.startswith('A') or codigo_cp.startswith('1'):
                naturaleza = 'ACTIVO'
            elif codigo_cp.startswith('P') or codigo_cp.startswith('2'):
                naturaleza = 'PASIVO'
            elif codigo_cp.startswith('C') or codigo_cp.startswith('3') or codigo_cp.startswith('4'):
                naturaleza = 'PATRIMONIO'
            elif codigo_cp.startswith('G'):
                naturaleza = 'GASTO'
            elif codigo_cp.startswith('I'):
                naturaleza = 'INGRESO'
            else:
                naturaleza = 'PASIVO'

        # Calcular saldo según la normalidad
        if naturaleza == 'ACTIVO':
            saldo = (s.debe or Decimal('0.00')) - (s.haber or Decimal('0.00'))
        elif naturaleza == 'PASIVO' or naturaleza == 'PATRIMONIO':
            saldo = (s.haber or Decimal('0.00')) - (s.debe or Decimal('0.00'))
        elif naturaleza == 'GASTO':
            # Gastos: normalidad en el Debe (gasto = debe - haber)
            saldo = (s.debe or Decimal('0.00')) - (s.haber or Decimal('0.00'))
        elif naturaleza == 'INGRESO':
            # Ingresos: normalidad en el Haber (ingreso = haber - debe)
            saldo = (s.haber or Decimal('0.00')) - (s.debe or Decimal('0.00'))
        else:
            saldo = Decimal('0.00')

        if saldo == Decimal('0.00'):
            continue

        row = {
            'codigo': s.codigo,
            'nombre': s.nombre,
            'saldo': saldo,
        }

        if naturaleza == 'ACTIVO':
            activos.append(row)
            total_activos += saldo
        elif naturaleza == 'PASIVO':
            pasivos.append(row)
            total_pasivos += saldo
        elif naturaleza == 'PATRIMONIO':
            patrimonio.append(row)
            total_patrimonio += saldo
        elif naturaleza == 'GASTO':
            gastos_total += saldo
        elif naturaleza == 'INGRESO':
            ingresos_total += saldo

    # Calcular utilidad del ejercicio (Ingresos - Gastos)
    utilidad = ingresos_total - gastos_total
    patrimonio_total_with_utilidad = total_patrimonio + utilidad

    # Suma explícita de Pasivo + Patrimonio (usar Decimal en la vista evita problemas de formato en plantilla)
    pasivos_plus_patrimonio = total_pasivos + patrimonio_total_with_utilidad

    context = {
        'periodos': periodos,
        'periodo': periodo,
        'selected_periods': [p.pk for p in (selected_periods_qs or [])],
        'mostrar_datos': mostrar_datos,
        'activos': activos,
        'pasivos': pasivos,
        'patrimonio': patrimonio,
        'activos_total': total_activos,
        'pasivos_total': total_pasivos,
        'patrimonio_total': total_patrimonio,
        'patrimonio_total_with_utilidad': patrimonio_total_with_utilidad,
        'pasivos_plus_patrimonio': pasivos_plus_patrimonio,
        'utilidad': utilidad,
        'hay_periodos_cerrados': hay_periodos_cerrados,
    }
    # Exportar CSV si se solicita
    export_param = request.GET.get('export')
    if export_param == 'csv':
        # Construir CSV con secciones: Activos, Pasivos, Patrimonio
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['Balance General'])
        # Cabecera de periodos (puede ser uno o varios)
        if selected_periods_qs is not None and selected_periods_qs.exists():
            names = [f"{p.nombre} ({p.fecha_inicio} a {p.fecha_fin})" for p in selected_periods_qs]
            writer.writerow([f'Periodos: {", ".join(names)}'])
        elif periodo:
            writer.writerow([f'Periodo: {periodo.nombre} ({periodo.fecha_inicio} a {periodo.fecha_fin})'])
        writer.writerow([])

        # Activos
        writer.writerow(['ACTIVOS'])
        writer.writerow(['Código', 'Cuenta', 'Saldo'])
        for a in activos:
            writer.writerow([a.get('codigo'), a.get('nombre'), f"{abs(a.get('saldo')):.2f}"])
        writer.writerow(['', 'Total Activos', f"{abs(total_activos):.2f}"])
        writer.writerow([])

        # Pasivos
        writer.writerow(['PASIVOS'])
        writer.writerow(['Código', 'Cuenta', 'Saldo'])
        for p in pasivos:
            writer.writerow([p.get('codigo'), p.get('nombre'), f"{abs(p.get('saldo')):.2f}"])
        writer.writerow(['', 'Total Pasivos', f"{abs(total_pasivos):.2f}"])
        writer.writerow([])

        # Patrimonio
        writer.writerow(['PATRIMONIO'])
        writer.writerow(['Código', 'Cuenta', 'Saldo'])
        for t in patrimonio:
            writer.writerow([t.get('codigo'), t.get('nombre'), f"{abs(t.get('saldo')):.2f}"])
        # Añadir utilidad del ejercicio si existe (mostrar sin signo)
        if utilidad != Decimal('0.00'):
            writer.writerow(['', 'Utilidad del ejercicio', f"{abs(utilidad):.2f}"])
        writer.writerow(['', 'Total Patrimonio', f"{abs(total_patrimonio):.2f}"])
        writer.writerow([])

        # Pasivos + Patrimonio (incluyendo utilidad)
        writer.writerow(['Pasivos + Patrimonio', f"{abs(total_pasivos + patrimonio_total_with_utilidad):.2f}"])
        writer.writerow(['Activos', f"{abs(total_activos):.2f}"])
        writer.writerow(['Diferencia', f"{abs(total_activos - (total_pasivos + patrimonio_total_with_utilidad)):.2f}"])

        resp = HttpResponse(buf.getvalue(), content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename="balance_general_cerrado.csv"'
        return resp

    return render(request, 'balance_general_cerrado.html', context)

