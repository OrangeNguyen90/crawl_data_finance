from django.contrib import admin
from marketdata import models

for model in (models.DataSource, models.Instrument, models.SourceInstrumentMapping,
              models.CotReport, models.FuturesDailyStatistic, models.OhlcvBar,
              models.RawDataFile, models.CollectorJob, models.DataQualityIssue,
              models.DatasetRegistry, models.CollectorCheckpoint, models.CollectorLock,
              models.SourceSchedule, models.QuarantinedRecord):
    admin.site.register(model)
