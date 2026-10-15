package `in`.personal.agent

import android.Manifest
import android.app.KeyguardManager
import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private var unlocked by mutableStateOf(false)
    private val unlock = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        unlocked = it.resultCode == RESULT_OK
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF285F52), secondary = Color(0xFF52665D),
                background = Color(0xFFF7F8F3), surface = Color(0xFFF7F8F3))) {
                Surface(Modifier.fillMaxSize()) {
                    if (unlocked) AgentApp() else Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center) {
                        Text("Your personal space", style = MaterialTheme.typography.headlineMedium)
                        Spacer(Modifier.height(16.dp))
                        Text("Unlock your device to access notes, tasks and call details.")
                        Button(onClick = { authenticate() }) { Text("Unlock") }
                    }
                }
            }
        }
        authenticate()
    }
    private fun authenticate() {
        val keyguard = getSystemService(KeyguardManager::class.java)
        if (!keyguard.isDeviceSecure) {
            startActivity(Intent(android.provider.Settings.ACTION_SECURITY_SETTINGS)); return
        }
        @Suppress("DEPRECATION")
        val intent = keyguard.createConfirmDeviceCredentialIntent("Personal Agent", "Unlock your private workspace")
        if (intent != null) unlock.launch(intent)
    }
    private var backgroundAt = 0L
    override fun onStop() { super.onStop(); backgroundAt = System.currentTimeMillis() }
    override fun onRestart() {
        super.onRestart()
        if (System.currentTimeMillis() - backgroundAt > 60_000 || getSystemService(KeyguardManager::class.java).isKeyguardLocked) unlocked = false
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun AgentApp(model: AgentModel = viewModel()) {
    var tab by remember { mutableIntStateOf(0) }
    val message by model.message.collectAsState()
    val busy by model.busy.collectAsState()
    val proposal by model.proposal.collectAsState()
    val snack = remember { SnackbarHostState() }
    LaunchedEffect(message) { if (message.isNotBlank()) { snack.showSnackbar(message); model.message.value = "" } }
    val tabs = listOf("Assistant", "My day", "Notes", "Calls", "Settings")
    val icons = listOf(Icons.Outlined.ChatBubbleOutline, Icons.Outlined.CheckCircleOutline, Icons.Outlined.Description,
        Icons.Outlined.Phone, Icons.Outlined.Settings)
    Scaffold(topBar = { TopAppBar(title = { Column {
        Text(tabs[tab], style = MaterialTheme.typography.headlineSmall)
        Text("PERSONAL AGENT · FOUNDATION", style = MaterialTheme.typography.labelSmall)
    } }) }, bottomBar = {
        NavigationBar { tabs.forEachIndexed { i, title -> NavigationBarItem(selected = tab == i, onClick = { tab = i },
            icon = { Icon(icons[i], contentDescription = title) }, label = { Text(title) }) } }
    }, snackbarHost = { SnackbarHost(snack) }) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            when (tab) {
                0 -> AssistantScreen(model)
                1 -> ItemsScreen(model, "task")
                2 -> ItemsScreen(model, "note")
                3 -> CallsScreen(model)
                4 -> SettingsScreen(model)
            }
        }
    }
    proposal?.let { p ->
        val detail = p.getJSONObject("proposal")
        AlertDialog(onDismissRequest = { model.proposal.value = null }, title = { Text("Review and confirm") },
            text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (p.getString("kind") == "budget") {
                    Text("Authorize an additional ₹${detail.getInt("amount_paise") / 100.0} for ${detail.getString("period")}?")
                    Text("This increases the permitted budget. It does not make a payment.")
                } else {
                    Text(if (p.optBoolean("simulation", true)) "SIMULATION · Google Calendar is not connected." else "This will change Google Calendar.")
                    Text("Conflicts: ${p.opt("conflicts")}")
                    Text(detail.getString("title"), style = MaterialTheme.typography.titleMedium)
                    Text("${detail.getString("start")} → ${detail.getString("end")}")
                    Text("${detail.getString("timezone")} · ${detail.getString("calendar_id")} · No attendees")
                }
            } }, confirmButton = { TextButton(enabled = !busy, onClick = model::confirm) { Text("Confirm") } },
            dismissButton = { TextButton(onClick = { model.proposal.value = null }) { Text("Cancel") } })
    }
}
