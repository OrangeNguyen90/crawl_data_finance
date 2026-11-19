from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from marketdata import dashboard

urlpatterns = [path("admin/", admin.site.urls), path("api/v1/", include("marketdata.urls"))]
urlpatterns += [path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
                path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api-docs")]
urlpatterns += [path("", dashboard.dashboard, name="dashboard"), path("collectors/action/", dashboard.action, name="collector-action")]
