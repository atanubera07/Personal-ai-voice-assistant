package `in`.personal.agent

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.room.*
import kotlinx.coroutines.flow.Flow
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Encrypt content before it reaches Room, preferences, or their write-ahead logs. */
class Vault {
    companion object { private val keyLock = Any() }
    private fun key(): SecretKey = synchronized(keyLock) {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("personal-agent-v1", null) as? SecretKey)?.let { return@synchronized it }
        KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("personal-agent-v1", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    @Synchronized fun seal(text: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        return Base64.encodeToString(cipher.iv + cipher.doFinal(text.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
    }
    @Synchronized fun open(text: String): String {
        val bytes = Base64.decode(text, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        }
        return String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
    }
}

@Entity(tableName = "personal_items")
data class PersonalItem(
    @PrimaryKey val id: String = UUID.randomUUID().toString(),
    val kind: String,
    val content: String,
    val done: Boolean = false,
    val dueAt: Long? = null,
    val timezone: String? = null,
    val reminderState: String = "DRAFT",
    val createdAt: Long = System.currentTimeMillis()
)

@Dao interface ItemDao {
    @Query("SELECT * FROM personal_items ORDER BY createdAt DESC") fun observe(): Flow<List<PersonalItem>>
    @Query("SELECT * FROM personal_items WHERE id = :id") suspend fun get(id: String): PersonalItem?
    @Upsert suspend fun save(item: PersonalItem)
    @Query("DELETE FROM personal_items WHERE id = :id") suspend fun delete(id: String)
}
@Database(entities = [PersonalItem::class], version = 1, exportSchema = false)
abstract class AgentDatabase : RoomDatabase() {
    abstract fun items(): ItemDao
    companion object {
        @Volatile private var instance: AgentDatabase? = null
        fun get(context: Context): AgentDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(context.applicationContext, AgentDatabase::class.java, "personal.db")
                .build().also { instance = it }
        }
    }
}

class ConnectionSettings(context: Context) {
    private val prefs = context.getSharedPreferences("connection", Context.MODE_PRIVATE)
    private val vault = Vault()
    var url: String
        get() = prefs.getString("url", "") ?: ""
        set(value) { prefs.edit().putString("url", value.trimEnd('/')).apply() }
    var token: String
        get() = prefs.getString("token", null)?.let { runCatching { vault.open(it) }.getOrDefault("") } ?: ""
        set(value) { if (value.isBlank()) prefs.edit().remove("token").apply() else prefs.edit().putString("token", vault.seal(value)).apply() }
    val deviceId: String = prefs.getString("device", null) ?: UUID.randomUUID().toString().also {
        prefs.edit().putString("device", it).apply()
    }
}
