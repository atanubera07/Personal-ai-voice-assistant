package `in`.personal.agent

import android.app.role.RoleManager
import android.content.Intent
import android.provider.ContactsContract
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
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

@Composable fun CallsScreen(model: AgentModel) {
    val calls by model.calls.collectAsState()
    val status by model.status.collectAsState()
    val busy by model.busy.collectAsState()
    var deleteId by remember { mutableStateOf<String?>(null) }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Intro("Stay in the loop.", "Live calling is not connected. Provider eligibility, Airtel forwarding, takeover and costs still require verification.") }
        item { OutlinedButton(enabled = !busy, onClick = model::refresh) { Text("Refresh calls") } }
        if (status?.optBoolean("simulation") == true) item { Text("SIMULATION · These are synthetic calls, not telephone conversations.", style = MaterialTheme.typography.labelLarge) }
        if (calls.isEmpty()) item { Text("No calls to show. Connect the backend in Settings, then run the local call simulator.", Modifier.padding(vertical = 24.dp)) }
        items(calls, key = { it.getString("id") }) { call ->
            OutlinedCard(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (call.optBoolean("urgent")) "Urgent callback" else "Call", style = MaterialTheme.typography.titleLarge)
                Text("${call.optString("category", "Unknown")} · ${call.getString("phase")}", style = MaterialTheme.typography.labelMedium)
                if (!call.isNull("summary")) Text(call.getString("summary"))
                else Text("No final summary available.")
                if (!call.isNull("urgency_reason")) Text(call.getString("urgency_reason"))
                Text("Recording: ${call.optString("recording")} · No audio stored in simulation", style = MaterialTheme.typography.bodySmall)
                if (call.optString("phase") == "AI_ACTIVE") {
                    Text("Takeover unavailable until provider media and stop-recording gates are verified.", style = MaterialTheme.typography.bodySmall)
                }
                if (call.optString("phase") in listOf("ENDED", "FAILED_ROUTED")) TextButton(onClick = { deleteId = call.getString("id") }) { Text("Delete summary") }
            } }
        }
        item { Spacer(Modifier.height(16.dp)) }
    }
    deleteId?.let { id -> AlertDialog(onDismissRequest = { deleteId = null }, title = { Text("Delete this call summary?") },
        text = { Text("The summary and private details will be removed from the backend. This cannot be undone.") },
        confirmButton = { TextButton(onClick = { model.deleteCall(id); deleteId = null }) { Text("Delete") } },
        dismissButton = { TextButton(onClick = { deleteId = null }) { Text("Cancel") } }) }
}

@Composable fun SettingsScreen(model: AgentModel) {
    var url by remember { mutableStateOf(model.settings.url) }
    var secret by remember { mutableStateOf("") }
    var amount by remember { mutableStateOf("") }
    var number by remember { mutableStateOf("") }
    var name by remember { mutableStateOf("") }
    var category by remember { mutableStateOf("Unknown") }
    var phrase by remember { mutableStateOf("") }
    val budget by model.budget.collectAsState()
    val status by model.status.collectAsState()
    val busy by model.busy.collectAsState()
    val context = LocalContext.current
    val role = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        result.data?.data?.let { uri ->
            runCatching { context.contentResolver.query(uri, arrayOf(ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) { number = cursor.getString(0); name = cursor.getString(1) }
            } }.onFailure { model.message.value = "Unable to read selected contact." }
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Intro("You stay in control.", "Connect your backend, choose what to share and review spending.")
        Text("Backend connection", style = MaterialTheme.typography.titleLarge)
        OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth(), label = { Text("HTTPS backend URL") }, singleLine = true)
        OutlinedTextField(secret, { secret = it }, Modifier.fillMaxWidth(), label = { Text("One-use pairing token (first connection)") }, visualTransformation = PasswordVisualTransformation(), singleLine = true)
        Text("First connection: enter a five-minute pairing token from your server. After pairing, leave it empty to sign in with this device. Sessions expire after 15 minutes.", style = MaterialTheme.typography.bodySmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = !busy && url.isNotBlank(), onClick = { model.signIn(url, secret); secret = "" }) { Text("Connect") }
            OutlinedButton(onClick = model::signOut) { Text("Sign out") }
        }
        status?.let { Text(if (it.optBoolean("simulation")) "Connected to simulation. No live provider, speech or Google Calendar." else "Foundation connected. Live integrations are not qualified.") }
        HorizontalDivider()
        Text("Monthly budget", style = MaterialTheme.typography.titleLarge)
        budget?.let { b ->
            Text("₹${b.getInt("authorized_limit_paise") / 100.0} authorized · ${b.getString("period")}", style = MaterialTheme.typography.headlineSmall)
            Text("Confirmed ₹${b.getInt("confirmed_paise") / 100.0} · Estimated ₹${b.getInt("estimated_paise") / 100.0} · Reserved ₹${b.getInt("reserved_paise") / 100.0}")
            Text("External fees remain unknown. ₹500 compliance is unverified. Pausing AI does not guarantee zero carrier charges.", style = MaterialTheme.typography.bodySmall)
        } ?: Text("Connect to view the budget. Default authorization: ₹500/month.")
        OutlinedTextField(amount, { amount = it }, label = { Text("Additional authorization (₹)") })
        OutlinedButton(enabled = !busy && amount.isNotBlank(), onClick = { model.budgetProposal(amount) }) { Text("Review increase") }
        HorizontalDivider()
        Text("Contacts & privacy", style = MaterialTheme.typography.titleLarge)
        Text("Only contacts you select are shared with your backend. Caller ID is advisory; never share passwords, addresses, financial details or private calendar information.")
        OutlinedButton(onClick = { picker.launch(Intent(Intent.ACTION_PICK, ContactsContract.CommonDataKinds.Phone.CONTENT_URI)) }) { Text("Pick one contact") }
        OutlinedTextField(name, { name = it }, label = { Text("Display name") })
        OutlinedTextField(number, { number = it }, label = { Text("Number, including +country code") })
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) { listOf("Family", "Friends").forEach { value ->
            FilterChip(selected = category == value, onClick = { category = value }, label = { Text(value) })
        } }
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) { listOf("Work", "Unknown").forEach { value ->
            FilterChip(selected = category == value, onClick = { category = value }, label = { Text(value) })
        } }
        OutlinedButton(enabled = !busy, onClick = { model.contact(number, name, category) }) { Text("Save selected contact") }
        OutlinedTextField(phrase, { phrase = it }, label = { Text("Approved basic phrase for $category") }, supportingText = { Text("Replaces the phrase for this category. Empty text clears it.") })
        OutlinedButton(enabled = !busy, onClick = { model.disclosure(category, phrase) }) { Text("Approve phrase") }
        HorizontalDivider()
        Text("Android assistant", style = MaterialTheme.typography.titleLarge)
        Text("You can request the default assistant role. Background wake word and Infinix XOS behavior still need testing.")
        OutlinedButton(onClick = {
            val manager = context.getSystemService(RoleManager::class.java)
            if (manager.isRoleAvailable(RoleManager.ROLE_ASSISTANT)) role.launch(manager.createRequestRoleIntent(RoleManager.ROLE_ASSISTANT))
            else model.message.value = "The assistant role is unavailable on this device."
        }) { Text("Choose default assistant") }
        Text("Local data is encrypted and excluded from backups. Losing this device or its Keystore key may make notes and tasks unrecoverable.", style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(16.dp))
    }
}
