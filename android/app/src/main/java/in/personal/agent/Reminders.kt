package `in`.personal.agent

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import java.util.concurrent.TimeUnit

object Reminders {
    fun schedule(context: Context, item: PersonalItem) {
        val due = item.dueAt ?: return
        val work = OneTimeWorkRequestBuilder<ReminderWorker>()
            .setInitialDelay((due - System.currentTimeMillis()).coerceAtLeast(0), TimeUnit.MILLISECONDS)
            .setInputData(workDataOf("id" to item.id)).build()
        WorkManager.getInstance(context).enqueueUniqueWork("reminder-${item.id}", ExistingWorkPolicy.REPLACE, work)
    }
    fun cancel(context: Context, id: String) { WorkManager.getInstance(context).cancelUniqueWork("reminder-$id") }
}
class ReminderWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val id = inputData.getString("id") ?: return Result.failure()
        val dao = AgentDatabase.get(applicationContext).items()
        val item = dao.get(id) ?: return Result.success()
        if (item.done || item.reminderState != "SCHEDULED") return Result.success()
        // A replaced worker must not deliver a newly edited reminder early.
        if ((item.dueAt ?: Long.MAX_VALUE) > System.currentTimeMillis() + 1000) return Result.success()
        val allowed = Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(applicationContext,
            Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        if (!allowed || !manager.areNotificationsEnabled()) {
            dao.save(item.copy(reminderState = "MISSED")); return Result.success()
        }
        manager.createNotificationChannel(NotificationChannel("reminders", "Private reminders", NotificationManager.IMPORTANCE_DEFAULT))
        val open = android.app.PendingIntent.getActivity(applicationContext, 0,
            android.content.Intent(applicationContext, MainActivity::class.java), android.app.PendingIntent.FLAG_IMMUTABLE)
        manager.notify(id.hashCode(), NotificationCompat.Builder(applicationContext, "reminders")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm).setContentTitle("A reminder is due")
            .setContentText("Open Personal Agent to view it.").setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(open).setAutoCancel(true).build())
        dao.save(item.copy(reminderState = "DELIVERED"))
        return Result.success()
    }
}
