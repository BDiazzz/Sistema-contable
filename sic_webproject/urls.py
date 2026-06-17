"""
URL configuration for sic_webproject project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from sic_webapp import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('catalogo/', views.catalogo, name='catalogo'),
    path('estado-capital/', views.estado_capital, name='estado_capital'),
    path('estado-resultado/', views.estado_resultado, name='estado_resultado'),
    path('hoja-trabajo/', views.hoja_trabajo, name='hoja_trabajo'),
    path('registrar/normal/', views.registrar_transaccion, 
         {'tipo_valor': 'NORMAL'}, 
         name='registrar_diario'),
    path('registrar/ajuste/', views.registrar_transaccion, 
         {'tipo_valor': 'AJUSTE'},
         name='registrar_ajuste'),
    path('estadoCapital/', views.estado_capital, name='estado_capital'),
    path('estadoResultado/', views.estado_resultado, name='estado_resultado'),
    path('catalogo/', views.catalogo, name='catalogo'),
    path(
        'reportes/balance-ajustado/', 
        views.balance_comprobacion_ajustado, 
        name='balance_ajustado'
    ),
    path('costos/', views.costos, name='costos'),
    path('api/check-iva/', views.check_cuenta_iva_api, name='check_cuenta_iva_api'),
    path('libro-mayor/', views.libro_mayor, name='libro_mayor'),
    path('libro-mayor/cerrar-periodo/', views.cerrar_periodo_contable, name='cerrar_periodo'),
    path('libro-mayor/crear-periodo/', views.crear_periodo_contable, name='crear_periodo'),
    path('hoja-trabajo/balanceComprobacion/', views.balanceComprobacion, name='balanceComprobacion'),
    path('hoja-trabajo/balance-general-cerrado/', views.balance_general_cerrado, name='balance_general_cerrado'),
]
