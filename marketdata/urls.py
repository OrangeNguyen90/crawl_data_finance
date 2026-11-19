from django.urls import path
from marketdata import views

urlpatterns = [
    path("sources/", views.SourceList.as_view()),
    path("instruments/", views.InstrumentList.as_view()),
    path("cot/", views.CotList.as_view()),
    path("open-interest/", views.OpenInterestList.as_view()),
    path("ohlcv/", views.OhlcvList.as_view()),
    path("collector/jobs/", views.JobList.as_view()),
    path("collectors/jobs/", views.JobList.as_view()),
    path("collectors/actions/", views.CollectorAction.as_view()),
    path("overview/", views.Overview.as_view()),
    path("export/<str:dataset>/", views.Export.as_view()),
    path("data-quality/", views.QualityList.as_view()),
    path("datasets/", views.DatasetList.as_view()),
    path("health/", views.Health.as_view()),
]
