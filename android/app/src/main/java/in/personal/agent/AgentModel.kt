package `in`.personal.agent

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.time.LocalDateTime
import java.time.ZoneId

class AgentModel(app: Application) : AndroidViewModel(app) {
    val settings = ConnectionSettings(app)
    val api = Backend(settings)
    private val dao = AgentDatabase.get(app).items()
    private val vault = Vault()
    val items = dao.observe().map { rows -> rows.map { it.copy(content = runCatching { vault.open(it.content) }
        .getOrDefault("Unable to decrypt. Device key is unavailable.")) } }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    val message = MutableStateFlow("")
    val busy = MutableStateFlow(false)
    val calls = MutableStateFlow<List<JSONObject>>(emptyList())
    val budget = MutableStateFlow<JSONObject?>(null)
    val status = MutableStateFlow<JSONObject?>(null)
    val proposal = MutableStateFlow<JSONObject?>(null)

    fun run(action: suspend () -> Unit) {
        viewModelScope.launch {
            busy.value = true
            try { action() } catch (e: Exception) { message.value = e.message ?: "Action failed. Try again." }
            finally { busy.value = false }
        }
    }
    fun save(kind: String, text: String, existing: PersonalItem? = null, dueText: String = "") = run {
        check(text.isNotBlank()) { "Enter some text first." }
        val zone = ZoneId.systemDefault()
        val due = if (dueText.isNotBlank()) LocalDateTime.parse(dueText).atZone(zone).toInstant().toEpochMilli() else null
        check(due == null || due > System.currentTimeMillis()) { "Choose a future reminder time." }
        val item = (existing ?: PersonalItem(kind = kind, content = "")).copy(content = vault.seal(text.trim()),
            dueAt = due, timezone = if (due != null) zone.id else null, reminderState = if (due != null) "SCHEDULED" else "DRAFT")
        dao.save(item)
        if (due != null) Reminders.schedule(getApplication(), item) else Reminders.cancel(getApplication(), item.id)
        message.value = if (due != null) "Saved. Reminder timing is approximate." else "Saved on this device."
    }
    fun toggle(item: PersonalItem) = run {
        dao.save(item.copy(content = vault.seal(item.content), done = !item.done,
            reminderState = if (!item.done) "COMPLETED" else "DRAFT"))
        Reminders.cancel(getApplication(), item.id)
    }
    fun delete(item: PersonalItem) = run {
        dao.delete(item.id); Reminders.cancel(getApplication(), item.id)
    }
    fun signIn(url: String, pairingToken: String) = run {
        settings.token = ""
        settings.url = url
        val result = if (pairingToken.isNotBlank()) {
            api.request("/v1/auth/enroll", "POST", JSONObject().put("device_id", settings.deviceId)
                .put("pairing_token", pairingToken).put("public_key", DeviceIdentity.publicKey())
                .put("signature", DeviceIdentity.sign("personal-agent-enroll-v1\n${settings.deviceId}\n$pairingToken")))
        } else {
            val challenge = api.request("/v1/auth/challenge", "POST", JSONObject().put("device_id", settings.deviceId))
            api.request("/v1/auth/device-session", "POST", JSONObject().put("device_id", settings.deviceId)
                .put("challenge_id", challenge.getString("id"))
                .put("signature", DeviceIdentity.sign("personal-agent-session-v1\n${challenge.getString("id")}\n${challenge.getString("nonce")}")))
        }
        settings.token = result.getString("access_token")
        refreshNow()
        message.value = "Connected with device proof. Session lasts 15 minutes."
    }
    fun signOut() = run {
        try {
            if (settings.token.isNotBlank()) api.request("/v1/auth/logout", "POST")
            message.value = "Signed out. Existing device sessions revoked."
        } finally {
            settings.token = ""; calls.value = emptyList(); budget.value = null; status.value = null
        }
    }
    suspend fun refreshNow() {
        status.value = api.request("/v1/status")
        budget.value = api.request("/v1/budget/current")
        val array = api.request("/v1/calls").getJSONArray("items")
        calls.value = (0 until array.length()).map { array.getJSONObject(it) }
    }
    fun refresh() = run { refreshNow() }
    fun deleteCall(id: String) = run { api.request("/v1/calls/$id", "DELETE"); refreshNow() }
    fun budgetProposal(amount: String) = run {
        val paise = amount.toBigDecimal().multiply(100.toBigDecimal()).intValueExact()
        val period = api.request("/v1/budget/current").getString("period")
        proposal.value = api.request("/v1/budget/approvals", "POST", JSONObject().put("period", period).put("amount_paise", paise))
            .put("kind", "budget")
    }
    fun confirm() = run {
        val p = proposal.value ?: return@run
        val path = if (p.getString("kind") == "budget") "/v1/budget/approvals" else "/v1/calendar/mutation-proposals"
        api.request("$path/${p.getString("id")}/confirm", "POST", JSONObject().put("nonce", p.getString("nonce")))
        proposal.value = null
        refreshNow()
        message.value = "Confirmed${if (p.optBoolean("simulation", status.value?.optBoolean("simulation") ?: false)) " in simulation" else ""}."
    }
    fun calendar(title: String, start: String, end: String) = run {
        val zone = ZoneId.systemDefault()
        val startTime = LocalDateTime.parse(start).atZone(zone).toOffsetDateTime().toString()
        val endTime = LocalDateTime.parse(end).atZone(zone).toOffsetDateTime().toString()
        proposal.value = api.request("/v1/calendar/mutation-proposals", "POST", JSONObject()
            .put("operation", "create").put("calendar_id", status.value?.optString("calendar_id", "primary") ?: "primary").put("title", title)
            .put("start", startTime).put("end", endTime).put("timezone", zone.id)).put("kind", "calendar")
    }
    fun contact(number: String, name: String, category: String) = run {
        val normalized = number.replace(Regex("[\\s()\\-]"), "")
        api.request("/v1/contacts/priority/${java.util.UUID.randomUUID()}", "PUT", JSONObject()
            .put("number", normalized).put("display_name", name).put("category", category))
        message.value = "Selected contact saved. Caller identity remains unverified."
    }
    fun disclosure(category: String, phrase: String) = run {
        val current = api.request("/v1/disclosures").getJSONObject("items").optJSONObject(category)
        api.request("/v1/disclosures/$category", "PUT", JSONObject().put("version", current?.optInt("version") ?: 0)
            .put("phrases", org.json.JSONArray().apply { if (phrase.isNotBlank()) put(phrase.trim()) }))
        message.value = "Disclosure rule saved."
    }
}
