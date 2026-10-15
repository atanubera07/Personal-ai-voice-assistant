package `in`.personal.agent

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.os.Build
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import java.time.Instant
import java.time.ZoneId

@Composable fun Intro(title: String, text: String) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(title, style = MaterialTheme.typography.headlineSmall)
        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable fun ItemsScreen(model: AgentModel, kind: String) {
    val all by model.items.collectAsState()
    val items = all.filter { it.kind == kind }
    var editor by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf<PersonalItem?>(null) }
    var calendar by remember { mutableStateOf(false) }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Intro(if (kind == "task") "Make room for today." else "Keep a thought.",
            if (kind == "task") "Tasks and reminders stay on this device. Reminder delivery is approximate and depends on Android battery settings."
            else "Your notes are encrypted on this device. They are never sent to callers or a cloud model.") }
        item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { selected = null; editor = true }) { Text(if (kind == "task") "Add task" else "Write a note") }
            if (kind == "task") OutlinedButton(onClick = { calendar = true }) { Text("Calendar") }
        } }
        if (items.isEmpty()) item { Text(if (kind == "task") "Nothing on your list yet." else "No notes yet. Start with something you want to remember.", Modifier.padding(vertical = 24.dp)) }
        items(items, key = { it.id }) { item ->
            OutlinedCard(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row {
                    if (kind == "task") Checkbox(checked = item.done, onCheckedChange = { model.toggle(item) })
                    Text(item.content, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                }
                item.dueAt?.let { Text("${Instant.ofEpochMilli(it).atZone(ZoneId.of(item.timezone ?: "UTC"))} · ${item.reminderState}", style = MaterialTheme.typography.labelMedium) }
                Row { TextButton(onClick = { selected = item; editor = true }) { Text("Edit") }
                    TextButton(onClick = { model.delete(item) }) { Text("Delete") } }
            } }
        }
        item { Spacer(Modifier.height(16.dp)) }
    }
    if (editor) ItemEditor(kind, selected, onDismiss = { editor = false }, onSave = { text, due ->
        model.save(kind, text, selected, due); editor = false
    })
    if (calendar) CalendarEditor(model) { calendar = false }
}

@Composable fun ItemEditor(kind: String, item: PersonalItem?, onDismiss: () -> Unit, onSave: (String, String) -> Unit) {
    var text by remember { mutableStateOf(item?.content ?: "") }
    var due by remember { mutableStateOf(item?.dueAt?.let { Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDateTime().toString() } ?: "") }
    val notifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    var error by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(if (kind == "task") "Task" else "Note") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedTextField(text, { text = it }, label = { Text("Text") }, minLines = 3)
            if (kind == "task") {
                OutlinedTextField(due, { due = it }, label = { Text("Reminder (optional)") }, supportingText = { Text("Local time: 2026-10-16T09:30") })
                Text("Approximate delivery. Exact alarms and device validation are not enabled.", style = MaterialTheme.typography.bodySmall)
            }
            if (error.isNotEmpty()) Text(error, color = MaterialTheme.colorScheme.error)
        }
    }, confirmButton = { TextButton(onClick = {
        val valid = text.isNotBlank() && (due.isBlank() || runCatching {
            java.time.LocalDateTime.parse(due).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli() > System.currentTimeMillis()
        }.getOrDefault(false))
        if (!valid) error = "Enter text and a valid future reminder time."
        else {
            if (due.isNotBlank() && Build.VERSION.SDK_INT >= 33) notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
            onSave(text, due)
        }
    }) { Text("Save") } }, dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } })
}

@Composable fun AssistantScreen(model: AgentModel) {
    var input by remember { mutableStateOf("") }
    var response by remember { mutableStateOf("Try ‘task: Call the electrician’ or ‘note: Ideas for Sunday’. You review every action before it is saved.") }
    var pending by remember { mutableStateOf<Pair<String, String>?>(null) }
    var voiceConsent by remember { mutableStateOf(false) }
    var locale by remember { mutableStateOf("en-IN") }
    val context = LocalContext.current
    val voice = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (it.resultCode == Activity.RESULT_OK) input = it.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull() ?: ""
    }
    fun launchVoice() {
        runCatching { voice.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, locale).putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)) }
            .onFailure { response = "No speech recognition app is available. You can still type." }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Intro("A little less to remember.", "A private place for the next task or passing thought.")
        OutlinedCard { Text(response, Modifier.padding(20.dp)) }
        OutlinedTextField(input, { input = it }, Modifier.fillMaxWidth(), label = { Text("What would you like to remember?") }, minLines = 3)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                val kind = when { input.startsWith("task:", true) -> "task"; input.startsWith("note:", true) -> "note"; else -> "" }
                if (kind.isBlank() || input.substringAfter(':').isBlank()) response = "Start with ‘task:’ or ‘note:’. General AI chat is not connected yet."
                else pending = kind to input.substringAfter(':').trim()
            }) { Text("Review") }
            OutlinedButton(onClick = { voiceConsent = true }) { Text("Tap to talk") }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("en-IN", "hi-IN", "bn-IN").forEach {
            FilterChip(selected = locale == it, onClick = { locale = it }, label = { Text(it) })
        } }
        Text("Typed commands work offline. Speech uses your selected Android recognition service; language availability depends on that service. Background wake word remains unverified.", style = MaterialTheme.typography.bodySmall)
    }
    if (voiceConsent) AlertDialog(onDismissRequest = { voiceConsent = false }, title = { Text("Use Android speech recognition?") },
        text = { Text("Your chosen recognition service may process speech online even when offline recognition is preferred. This app does not save the audio. Continue only if you accept that service’s processing.") },
        confirmButton = { TextButton(onClick = { voiceConsent = false; launchVoice() }) { Text("Continue") } },
        dismissButton = { TextButton(onClick = { voiceConsent = false }) { Text("Cancel") } })
    pending?.let { (kind, text) -> AlertDialog(onDismissRequest = { pending = null }, title = { Text("Save $kind?") },
        text = { Text(text) }, confirmButton = { TextButton(onClick = { model.save(kind, text); pending = null; input = ""; response = "You can review saved items in ${if (kind == "task") "My day" else "Notes"}." }) { Text("Save") } },
        dismissButton = { TextButton(onClick = { pending = null }) { Text("Cancel") } }) }
}

@Composable fun CalendarEditor(model: AgentModel, close: () -> Unit) {
    val status by model.status.collectAsState()
    var title by remember { mutableStateOf("") }
    var start by remember { mutableStateOf("") }
    var end by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = close, title = { Text("Calendar proposal") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(if (status?.optBoolean("google_calendar") == true) "Review the exact event before confirming a change to Google Calendar." else "Google Calendar is not connected. This is a simulated calendar flow.")
            OutlinedTextField(title, { title = it }, label = { Text("Title") })
            OutlinedTextField(start, { start = it }, label = { Text("Start · YYYY-MM-DDTHH:MM") })
            OutlinedTextField(end, { end = it }, label = { Text("End · YYYY-MM-DDTHH:MM") })
            Text("Timezone: ${ZoneId.systemDefault().id}")
        }
    }, confirmButton = { TextButton(onClick = { model.calendar(title, start, end); close() }) { Text("Review proposal") } },
        dismissButton = { TextButton(onClick = close) { Text("Cancel") } })
}
