document.addEventListener('DOMContentLoaded', function() {
    
    // --- 1. CONFIGURACIÓN Y LECTURA DE DATOS ---
    const formElement = document.getElementById('transaction-form');
    if (!formElement) {
        console.error("Error: No se encontró el elemento #transaction-form.");
        return;
    }
    
    const config = {
        formPrefix: formElement.dataset.prefix,
        checkIvaUrl: formElement.dataset.checkIvaUrl,
        ivaCreditoCode: formElement.dataset.ivaCreditoCode,
        ivaDebitoCode: formElement.dataset.ivaDebitoCode,
        defaultPagoCode: formElement.dataset.defaultPagoCode,
        defaultCobroCode: formElement.dataset.defaultCobroCode,
        tasaIva: parseFloat(formElement.dataset.tasaIva)
    };

    // Elementos del DOM (jQuery)
    const $formsetContainer = $('#formset-container'); 
    const $managementForm = $(`#id_${config.formPrefix}-TOTAL_FORMS`);
    const $modoSelect = $('#modo-transaccion');
    const $addRowBtn = $('#add-row');

    // Estado del Formulario
    let totalForms = parseInt($managementForm.val());
    let emptyForm = $('.movement-row:first').clone(true); // Guardar plantilla

    const mainForm = $('#transaction-form'); 
    const submitButton = mainForm.find('button[type="submit"]');

    // --- 2. LÓGICA DE AUTOMATIZACIÓN ---
function resetFormForMode(newMode) {
        $formsetContainer.empty();
        totalForms = 0;
        $managementForm.val(0);

        if (newMode === 'manual') {
            $addRowBtn.show();
            // --- LÍNEA AÑADIDA ---
            // Mostrar la cabecera de la columna "Eliminar"
            $('thead').find('th:last-child').show();
            // --- FIN DE LA MODIFICACIÓN ---

            createNewManualRow(); // createNewManualRow() ya muestra la celda <td>
            createNewManualRow(); 
        } else {
            $addRowBtn.hide();
            // --- LÍNEA AÑADIDA ---
            // Ocultar la cabecera de la columna "Eliminar"
            $('thead').find('th:last-child').hide();
            // --- FIN DE LA MODIFICACIÓN ---

            const $mainRow = createNewManualRow();
            const $ivaRow = createNewManualRow();
            const $pagoRow = createNewManualRow();
            
            // --- BLOQUE MODIFICADO ---
            // Ocultamos explícitamente TODAS las CELDAS (<td>) de borrado
            $mainRow.find('.delete-row').parent('td').hide();
            $ivaRow.find('.delete-row').parent('td').hide();
            $pagoRow.find('.delete-row').parent('td').hide();
            // --- FIN DE LA MODIFICACIÓN ---
            
            lockRow($ivaRow, true, false); 
            lockRow($pagoRow, true, false); 

            if (newMode === 'compra') {
                $mainRow.find('.tipo-movimiento-select').val('Debe').prop('disabled', true);
                
                $ivaRow.find('.subcuenta-select').val(config.ivaCreditoCode).prop('disabled', true);
                $ivaRow.find('.tipo-movimiento-select').val('Debe').prop('disabled', true);
                
                $pagoRow.find('.subcuenta-select').val(config.defaultPagoCode).prop('disabled', false); 
                $pagoRow.find('.tipo-movimiento-select').val('Haber').prop('disabled', true);
            
            } else if (newMode === 'venta') {
                $mainRow.find('.tipo-movimiento-select').val('Haber').prop('disabled', true);
                $ivaRow.find('.subcuenta-select').val(config.ivaDebitoCode).prop('disabled', true);
                $ivaRow.find('.tipo-movimiento-select').val('Haber').prop('disabled', true);
                $pagoRow.find('.subcuenta-select').val(config.defaultCobroCode).prop('disabled', false);
                $pagoRow.find('.tipo-movimiento-select').val('Debe').prop('disabled', true);
            }
            
            $ivaRow.hide();
            $pagoRow.hide();
        }
        
        calculateTotals();
    }
/**
     * Bloquea campos de una fila.
     * @param {boolean} lockMonto - Si es true, bloquea el campo monto.
     * @param {boolean} lockAll - Si es true, bloquea todo (subcuenta, tipo, monto).
     */
    function lockRow($row, lockMonto, lockAll = false) {
        if (lockAll) {
            $row.find('.subcuenta-select, .tipo-movimiento-select, .monto-input').prop('disabled', true);
        } else {
            $row.find('.monto-input').prop('disabled', lockMonto);
        }
        // --- LÍNEA ELIMINADA ---
        // $row.find('.delete-row').toggle(!lockMonto); 
        // Ya no controlamos el botón desde aquí.
    }

    function runAutoCalculation() {
        const currentMode = $modoSelect.val();
        if (currentMode === 'manual') return;

        const $mainRow = $formsetContainer.find('.movement-row:eq(0)');
        const $ivaRow = $formsetContainer.find('.movement-row:eq(1)');
        const $pagoRow = $formsetContainer.find('.movement-row:eq(2)');
        
        const mainCuentaCode = $mainRow.find('.subcuenta-select').val();
        const mainMonto = parseFloat($mainRow.find('.monto-input').val()) || 0;

        if (!mainCuentaCode || mainMonto === 0) {
            $ivaRow.find('.monto-input').val('');
            $pagoRow.find('.monto-input').val('');
            $ivaRow.hide();
            $pagoRow.hide();
            calculateTotals();
            return;
        }

        $.get(config.checkIvaUrl, { codigo: mainCuentaCode }, function(response) {
            if (response.aplica_iva) {
                const ivaCalculado = (mainMonto * config.tasaIva).toFixed(2);
                const totalCalculado = (mainMonto * (1 + config.tasaIva)).toFixed(2);

                $ivaRow.find('.monto-input').val(ivaCalculado);
                $pagoRow.find('.monto-input').val(totalCalculado);
                
                $ivaRow.show();
                $pagoRow.show();

            } else { // No aplica IVA
                $ivaRow.find('.monto-input').val('');
                $pagoRow.find('.monto-input').val(mainMonto.toFixed(2));
                
                $ivaRow.hide();
                $pagoRow.show();
            }
            
            calculateTotals();
        });
    }

function createNewManualRow() {
        const newRow = emptyForm.clone(true);
        const prefix = config.formPrefix;
        
        newRow.find(':input').each(function() {
            const input = $(this);
            if (!input.is(':checkbox') && !input.is(':radio')) {
                input.val(''); 
            } else if (input.is(':checkbox')) {
                input.prop('checked', false);
            }
        });
        
        newRow.find('.total-debe, .total-haber').text('');
        newRow.find('.tipo-movimiento-select').val('Debe');
        
        lockRow(newRow, false, true); 
        lockRow(newRow, false, false);
        newRow.find('.subcuenta-select, .tipo-movimiento-select, .monto-input').prop('disabled', false);
        
        // Aseguramos que la CELDA (el <td> padre del botón) sea visible
        newRow.find('.delete-row').parent('td').show();


        updateElementIndex(newRow, prefix, totalForms);
        newRow.attr('id', prefix + '-' + totalForms + '-row');
        newRow.show();
        
        $formsetContainer.append(newRow); 
        
        totalForms++;
        $managementForm.val(totalForms);
        
        return newRow;
    }

    // --- 3. LÓGICA DE CÁLCULO ---

    mainForm.on('submit', function(e) {
        if (submitButton.is(':disabled')) {
            e.preventDefault(); 
            return false; 
        }
        
        $formsetContainer.find(':input').prop('disabled', false);

        $(this).append($('<input>', {
            type: 'hidden',
            name: 'modo-transaccion',
            value: $modoSelect.val()
        }));

        submitButton.prop('disabled', true);
        submitButton.html(
            `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Registrando...`
        );
    });

    function updateElementIndex(el, prefix, index) {
        const idRegex = new RegExp('(' + prefix + '-\\d+-)');
        const replacement = prefix + '-' + index + '-';

        const currentId = el.attr('id');
        if (currentId) {
            el.attr('id', currentId.replace(idRegex, replacement));
        }
        
        el.find(':input').each(function() {
            const input = $(this);
            if (input.attr('name')) {
                input.attr('name', input.attr('name').replace(idRegex, replacement));
            }
            if (input.attr('id')) {
                input.attr('id', input.attr('id').replace(idRegex, replacement));
            }
        });
    }
    
    function calculateTotals() {
        let totalDebe = 0.0;
        let totalHaber = 0.0;

        $('.movement-row').each(function() {
            const row = $(this);
            const montoInput = row.find('.monto-input');
            const tipoMovimiento = row.find('.tipo-movimiento-select').val();
            const deleteCheckbox = row.find('input[type="checkbox"][id$="-DELETE"]');
            
            if (deleteCheckbox.length && deleteCheckbox.is(':checked')) {
                row.find('.total-debe').text('0.00');
                row.find('.total-haber').text('0.00');
                return true; 
            }

            const monto = parseFloat(montoInput.val()) || 0.0;
            
            row.find('.total-debe').text('');
            row.find('.total-haber').text('');

            if (tipoMovimiento === 'Debe') {
                totalDebe += monto;
                row.find('.total-debe').text(monto.toFixed(2));
            } else if (tipoMovimiento === 'Haber') {
                totalHaber += monto;
                row.find('.total-haber').text(monto.toFixed(2));
            }
        });

        $('#grand-total-debe').text(totalDebe.toFixed(2));
        $('#grand-total-haber').text(totalHaber.toFixed(2));

        const difference = (totalDebe - totalHaber).toFixed(2);
        const diffElement = $('#total-difference');
        diffElement.text(difference);

        if (Math.abs(difference) > 0.005) { 
            diffElement.removeClass('text-success').addClass('text-danger');
        } else {
            diffElement.removeClass('text-danger').addClass('text-success');
        }
    }

    // --- 4. EVENT HANDLERS ---
    
    // (calculateTotals() se mueve al final, a la lógica de inicialización)

    $formsetContainer.on('change', '.monto-input, .tipo-movimiento-select, input[type="checkbox"][id$="-DELETE"]', function() {
        const currentMode = $modoSelect.val();
        if (currentMode === 'manual') {
            calculateTotals(); 
        }
    });

    $addRowBtn.click(function() {
        const currentMode = $modoSelect.val();
        if (currentMode === 'manual') {
            createNewManualRow();
            calculateTotals();
        } else {
            Swal.fire('Modo Automático', 'No puedes añadir filas manualmente en este modo.', 'warning');
        }
    });

    $formsetContainer.on('click', '.delete-row', function() {
        const currentMode = $modoSelect.val();
        if (currentMode !== 'manual') {
             Swal.fire('Modo Automático', 'No puedes eliminar filas manualmente en este modo.', 'warning');
             return;
        }

        const row = $(this).closest('.movement-row');
        const deleteInput = row.find('input[type="checkbox"][id$="-DELETE"]');
        
        if ($(this).data('existing')) {
            deleteInput.prop('checked', true);
            row.hide();
        } else {
            // No permitir borrar si quedan 2 filas o menos en modo manual
            if ($formsetContainer.find('.movement-row').length <= 2) {
                Swal.fire('Modo Manual', 'Debe haber al menos dos filas.', 'info');
                return;
            }
            row.remove();
            
            totalForms--;
            $managementForm.val(totalForms);
            
            $('.movement-row').each(function(index) {
                updateElementIndex($(this), config.formPrefix, index); 
            });
        }
        
        calculateTotals();
    });

    // --- NUEVOS EVENT HANDLERS PARA AUTOMATIZACIÓN ---

    $modoSelect.on('change', function() {
        resetFormForMode($(this).val());
    });

    $formsetContainer.on('change', '.subcuenta-select', function() {
        if ($modoSelect.val() !== 'manual') {
            runAutoCalculation();
        }
    });
    $formsetContainer.on('keyup change', '.monto-input', function() {
        if ($modoSelect.val() !== 'manual') {
            runAutoCalculation();
        }
    });


    // ===================================================================
    //  AQUÍ ESTÁ LA CORRECCIÓN 3.0 (INICIALIZACIÓN)
    // ===================================================================
    
    // Verificamos si el formset ya tiene formularios (es un POST fallido)
    // o si el número de filas renderizadas es mayor que 1 (formset 'extra=1')
    const initialFormsCount = parseInt($managementForm.val());
    const existingRows = $formsetContainer.find('.movement-row');
    const hasInitialData = existingRows.length > 0 && existingRows.find('.monto-input[value!=""]').length > 0;

    if (initialFormsCount > 1 || (initialFormsCount > 0 && hasInitialData) ) {
        // Es un POST fallido. No reseteamos.
        // Solo calculamos los totales con los datos que ya están.
        console.log("POST fallido detectado. Omitiendo reseteo.");
        calculateTotals();
        
        // Dejamos el modo en 'manual' por defecto para que el botón '+' funcione
        $modoSelect.val('manual'); 
        
    } else {
        // Es una carga GET limpia. Reseteamos al estado inicial.
        console.log("Carga GET limpia. Reseteando formulario.");
        resetFormForMode('manual');
    }
    // ===================================================================

});