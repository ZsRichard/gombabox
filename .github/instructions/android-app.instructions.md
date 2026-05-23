---
name: android-app
description: "Use when: developing Android application for GombaBox. Context for API integration, data models, and mushroom growing requirements."
applyTo: "**/src/**/*.{java,kt,gradle}"
---

# GombaBox Android App Development Guide

## Project Context

**GombaBox** is an automated oyster mushroom growing system with Raspberry Pi backend. The Android app provides real-time monitoring and control via REST API.

### Hardware System
- **Controller**: Raspberry Pi 4/5
- **Sensors**: Temperature, humidity, pressure, CO2, light levels
- **Actuators**: Ventilation fan, humidifier, LED strip (controlled via GPIO relays)
- **Camera**: AI-powered mycelium coverage detection

---

## REST API Specification

### Base URL
```
http://{RASPBERRY_PI_IP}:5000/api
```

### Authentication
Currently stateless (no authentication implemented). Future: Session tokens.

---

## API Endpoints

### 1. **Measurements** (Sensor Data)

#### GET `/api/measurements`
Latest measurements with pagination.
```
Query params:
  - limit: int (default: 100, max: 1000)

Response: Array of measurement objects
[
  {
    "id": 1,
    "timestamp": "2026-05-04 14:30:45",
    "temperature": 22.5,
    "humidity": 78.3,
    "pressure": 1013.25,
    "co2": 450.5,
    "light": 2500.0
  }
]
```

#### GET `/api/measurements/latest`
Single most recent measurement.
```
Response:
{
  "id": 1,
  "timestamp": "2026-05-04 14:30:45",
  "temperature": 22.5,
  "humidity": 78.3,
  "pressure": 1013.25,
  "co2": 450.5,
  "light": 2500.0
}
```

#### GET `/api/measurements/history`
Historical data with time-range filtering.
```
Query params:
  - hours: int (default: 1, max: 720 = 30 days)

Response:
{
  "measurements": [...],
  "hours": 24,
  "count": 1440
}
```

---

### 2. **Camera / Mycelium Analysis**

#### GET `/api/camera/latest`
Latest mycelium coverage scan.
```
Response:
{
  "filename": "capture_2026050414300000.jpg",
  "url": "/captures/capture_2026050414300000.jpg",
  "analysis": "85.5"  // Percentage coverage
}
```

#### GET `/api/camera/captures`
Camera capture history with pagination.
```
Query params:
  - limit: int (default: 50, max: 500)

Response: Array
[
  {
    "id": 1,
    "timestamp": "2026-05-04 14:30:45",
    "filename": "capture_2026050414300000.jpg",
    "analysis_result": "85.5"
  }
]
```

#### GET `/api/camera/history`
Mycelium coverage trend over time.
```
Query params:
  - hours: int (default: 1, max: 720)

Response:
{
  "captures": [
    {"time": "2026-05-04 14:00", "analysis": "78.2"},
    {"time": "2026-05-04 14:30", "analysis": "79.1"}
  ],
  "count": 30
}
```

---

### 3. **System Settings & Control**

#### GET `/api/settings`
All system configuration values.
```
Response: Array
[
  {
    "key": "target_humidity",
    "value": "85",
    "description": "Target humidity percentage"
  },
  {
    "key": "target_temperature",
    "value": "22",
    "description": "Target temperature in Celsius"
  }
]
```

#### GET `/api/settings/{key}`
Single setting value.
```
Response:
{
  "key": "target_humidity",
  "value": "85",
  "description": "Target humidity percentage"
}
```

#### PUT `/api/settings/{key}`
Update a setting.
```
Request body:
{
  "value": "88"
}

Response: 200 OK with updated object
```

---

### 4. **Manual Relay Control**

#### **GET `/api/relay/{relay_id}`**
Get current state of a specific relay.
```
Path params:
  - relay_id: int (1, 2, or 3)
    * 1 = Ventilation Fan (GPIO 27)
    * 2 = Humidifier (GPIO 17)
    * 3 = LED Strip (GPIO 22)

Response:
{
  "relay_id": 1,
  "state": true
}
```

#### **POST `/api/relay/{relay_id}`**
Set relay state (true = ON, false = OFF).
```
Path params:
  - relay_id: int (1, 2, or 3)

Request body:
{
  "state": true
}

Response:
{
  "relay_id": 1,
  "state": true
}

Status codes:
  - 200: Success
  - 400: Invalid relay ID (must be 1, 2, or 3)
  - 500: Hardware control error
```

### **Relay Hardware Mapping**
| Relay ID | GPIO Pin | Function | Purpose |
|----------|----------|----------|---------|
| 1 | GPIO 27 | Ventilation Fan | Air circulation & CO2 control |
| 2 | GPIO 17 | Humidifier | Humidity control |
| 3 | GPIO 22 | LED Strip | Mushroom growth lighting |

**Note**: Relays use active-low logic (GPIO HIGH = OFF, GPIO LOW = ON)

---

### 5. **System Status & Control**

#### GET `/api/health`
Health check and system status.
```
Response:
{
  "status": "ok",
  "mode": "hardware",  // or "mock" if using simulated hardware
  "background_running": true
}
```

#### POST `/api/start`
Start background automation tasks (measurement cycle).
```
Response:
{
  "status": "started"
}
```

#### POST `/api/stop`
Stop background automation tasks.
```
Response:
{
  "status": "stopped"
}
```

#### POST `/api/restart`
Restart the gombabox systemd service (requires sudo).
```
Response:
{
  "status": "restarting"
}
```

#### GET `/api/phase`
Get the current growth phase and allowed values.
```
Response:
{
    "phase": "fruiting",
    "allowed": ["colonization", "fruiting"]
}
```

#### POST `/api/phase`
Set growth phase and trigger a service restart.
```
Request body:
{
  "phase": "colonization"  // or "fruiting"
}

Response:
{
  "status": "restarting",
  "phase": "colonization"
}

Valid phases:
  - "colonization": Mycelium growth phase (higher CO2, moderate light)
  - "fruiting": Mushroom fruiting phase (higher humidity, higher light)

Status codes:
    - 200: Success
    - 400: Missing phase parameter or invalid phase value
    - 500: Failed to handle growth phase
```

---

## Data Models for Android (Kotlin)

### MeasurementData
```kotlin
data class MeasurementData(
    val id: Int,
    val timestamp: String,
    val temperature: Float,
    val humidity: Float,
    val pressure: Float,
    val co2: Float,
    val light: Float
)
```

### CameraCapture
```kotlin
data class CameraCapture(
    val id: Int,
    val timestamp: String,
    val filename: String,
    val analysisResult: String  // Percentage as string (e.g., "85.5")
)
```

### Measurement History Response
```kotlin
data class MeasurementHistory(
    val measurements: List<MeasurementData>,
    val hours: Int,
    val count: Int
)
```

### Settings
```kotlin
data class SettingItem(
    val key: String,
    val value: String,
    val description: String
)
```

### RelayStatus
```kotlin
data class RelayStatus(
    val relayId: Int,
    val state: Boolean  // true = ON, false = OFF
)
```

### SystemHealth
```kotlin
data class SystemHealth(
    val status: String,  // "ok"
    val mode: String,    // "hardware" or "mock"
    val backgroundRunning: Boolean
)
```

### SystemResponse
```kotlin
data class SystemResponse(
    val status: String  // "started", "stopped", "restarting"
)
```

### GrowthPhaseResponse
```kotlin
data class GrowthPhaseResponse(
    val phase: String,
    val allowed: List<String>? = null,
    val status: String? = null
)
```

### GrowthPhaseRequest
```kotlin
data class GrowthPhaseRequest(
    val phase: String  // "colonization" or "fruiting"
)
```

---

## Android Development Requirements

### 1. **Networking**
- Use **Retrofit 2** for REST API calls
- Implement Kotlin **Coroutines** for async operations
- Handle network errors gracefully with try-catch blocks
- Implement automatic retry logic for transient failures

### 2. **UI Architecture**
- Use **MVVM** (Model-View-ViewModel) pattern
- **Jetpack Compose** OR XML Layout (project decision)
- **LiveData** or **StateFlow** for reactive updates
- ViewModel for managing UI state

### 3. **Data Persistence**
- Use **Room Database** for local cache
- Cache latest measurements for offline access
- Store user preferences (API URL, refresh rate)

### 4. **Real-Time Updates**
- Implement periodic polling (15-30 second intervals)
- OR use WebSocket for push updates (future enhancement)
- Handle screen rotation and lifecycle events properly

### 5. **UI Features - MVP**

#### Dashboard Screen
- Current sensor readings (temp, humidity, CO2, light)
- Mycelium coverage % with visual progress bar
- System status indicator (running/stopped)
- Last update timestamp

#### Graphs Screen
- Temperature trend (24-hour chart)
- Humidity trend (24-hour chart)
- CO2 level trend
- Mycelium coverage trend
- Time range selector (1h, 6h, 24h, 7d)

#### Controls Screen
- Manual relay toggle buttons (fan, humidifier, LED)
- Settings editor (target temperature, humidity, etc.)
- Relay status display

#### Camera Screen
- Latest mycelium image with timestamp
- Coverage percentage display
- Historical thumbnail gallery
- Save/share image functionality

---

## Development Checklist

### Phase 1: Setup & API Integration (Week 1-2)
- [ ] Android Studio project created (Kotlin + Gradle)
- [ ] Retrofit configured for API base URL
- [ ] Data classes modeled (MeasurementData, CameraCapture, RelayStatus, SystemHealth, etc.)
- [ ] API service interface defined
  - [ ] Measurement endpoints
  - [ ] Relay endpoints (GET & POST)
  - [ ] System health endpoint
  - [ ] System control endpoints (start, stop, restart)
- [ ] Dependency injection setup (Hilt or Manual)
- [ ] API connectivity test (display latest measurement)
- [ ] Relay state query test

### Phase 2: Dashboard & Graphs (Week 3-4)
- [ ] Main dashboard UI layout
- [ ] Real-time sensor data display
- [ ] Relay state display with visual indicators (ON/OFF badges)
- [ ] Chart library integrated (MPAndroidChart recommended)
- [ ] Measurement history API integration
- [ ] Periodic data refresh (every 30 seconds)
- [ ] System health status indicator

### Phase 3: Controls & Settings (Week 5)
- [ ] Manual relay control buttons (3 buttons for fan, humidifier, LED)
- [ ] Relay toggle animation/feedback
- [ ] Relay state sync with backend
- [ ] Settings editor interface
- [ ] Growth phase selector (colonization / fruiting)
- [ ] Settings persistence

### Phase 4: Camera & Polish (Week 6)
- [ ] Camera image download & display
- [ ] Mycelium coverage trend graph
- [ ] Image gallery with history
- [ ] System start/stop controls
- [ ] App icons & theming
- [ ] Error messages & offline support

---

## Configuration

### Constants to Define
```kotlin
object AppConfig {
    var API_BASE_URL = "http://192.168.1.100:5000"  // User-configurable
    const val MEASUREMENT_REFRESH_INTERVAL_MS = 30000  // 30 seconds
    const val GRAPH_TIME_RANGE_HOURS = 24
    const val IMAGE_CACHE_SIZE_MB = 100
}
```

### SharedPreferences Keys
- `api_base_url` - Raspberry Pi IP:Port
- `auto_refresh_enabled` - Boolean
- `refresh_interval_seconds` - Int
- `last_sync_timestamp` - Long

---

## Error Handling Strategy

1. **Network Errors**: Show retry button, cached data if available
2. **API Errors (4xx/5xx)**: Display user-friendly error message
3. **Timeout**: Auto-retry with exponential backoff
4. **Offline**: Graceful degradation with cached data
5. **Invalid Data**: Log error, skip display, continue polling

---

## Key Implementation Tips

1. **Start with Dashboard**: Get measurements flowing first
2. **Use Coroutines**: Never block UI thread
3. **Cache Aggressively**: Room DB + in-memory cache
4. **Test on Real Device**: Emulator may not handle WiFi well
5. **Battery Optimization**: Use WorkManager for background sync if needed
6. **Handle Lifecycle**: Cancel coroutines in onDestroy()

---

## Testing Strategy

- **Unit Tests**: API response parsing, data transformation
- **Integration Tests**: API connectivity, Room DB operations
- **UI Tests**: Compose previews or Espresso
- **Manual Testing**: Test on Raspberry Pi in actual lab

---

## Build Configuration (gradle)

```gradle
dependencies {
    // Retrofit
    implementation 'com.squareup.retrofit2:retrofit:2.10.0'
    implementation 'com.squareup.retrofit2:converter-gson:2.10.0'
    
    // Coroutines
    implementation 'org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.0'
    
    // Room
    implementation 'androidx.room:room-runtime:2.6.0'
    implementation 'androidx.room:room-ktx:2.6.0'
    
    // Jetpack
    implementation 'androidx.lifecycle:lifecycle-viewmodel-ktx:2.6.1'
    implementation 'androidx.lifecycle:lifecycle-runtime-ktx:2.6.1'
    
    // Charts
    implementation 'com.github.PhilJay:MPAndroidChart:v3.1.0'
}
```

---

---

## Relay Control Strategy

### Button Layout (Controls Screen)
```
┌─────────────────────────────────┐
│     RELAY CONTROL PANEL         │
├─────────────────────────────────┤
│  [Fan]       [Status: OFF]      │
│   Relay 1                       │
│  ┌──────────────────────┐       │
│  │    [Toggle Button]   │       │
│  └──────────────────────┘       │
├─────────────────────────────────┤
│  [Humidifier] [Status: ON]      │
│   Relay 2                       │
│  ┌──────────────────────┐       │
│  │    [Toggle Button]   │       │
│  └──────────────────────┘       │
├─────────────────────────────────┤
│  [LED]        [Status: OFF]     │
│   Relay 3                       │
│  ┌──────────────────────┐       │
│  │    [Toggle Button]   │       │
│  └──────────────────────┘       │
└─────────────────────────────────┘
```

### Implementation Pattern (Kotlin + Coroutines)
```kotlin
// ViewModel
class RelayViewModel(private val apiService: GombaBoxApiService) : ViewModel() {
    
    private val _relayStates = MutableLiveData<Map<Int, Boolean>>()
    val relayStates: LiveData<Map<Int, Boolean>> = _relayStates
    
    fun toggleRelay(relayId: Int) {
        viewModelScope.launch {
            try {
                val currentState = _relayStates.value?.get(relayId) ?: false
                val response = apiService.setRelayState(relayId, !currentState)
                
                // Update local state
                _relayStates.value = (_relayStates.value ?: emptyMap()).toMutableMap().apply {
                    put(relayId, response.state)
                }
            } catch (e: Exception) {
                // Handle error - show toast
            }
        }
    }
    
    fun getRelayState(relayId: Int) {
        viewModelScope.launch {
            try {
                val response = apiService.getRelayState(relayId)
                _relayStates.value = (_relayStates.value ?: emptyMap()).toMutableMap().apply {
                    put(relayId, response.state)
                }
            } catch (e: Exception) {
                // Handle error
            }
        }
    }
    
    fun pollAllRelays() {
        // Poll relay states every 30 seconds
        viewModelScope.launch {
            while (true) {
                try {
                    val states = mutableMapOf<Int, Boolean>()
                    for (id in listOf(1, 2, 3)) {
                        val response = apiService.getRelayState(id)
                        states[id] = response.state
                    }
                    _relayStates.value = states
                } catch (e: Exception) {
                    // Log error
                }
                delay(30000)  // 30 second interval
            }
        }
    }
}

// Retrofit Service Interface
interface GombaBoxApiService {
    
    @GET("relay/{relay_id}")
    suspend fun getRelayState(@Path("relay_id") relayId: Int): RelayStatus
    
    @POST("relay/{relay_id}")
    suspend fun setRelayState(
        @Path("relay_id") relayId: Int,
        @Body request: SetRelayRequest
    ): RelayStatus
    
    @GET("health")
    suspend fun getHealth(): SystemHealth
    
    @POST("start")
    suspend fun startSystem(): SystemResponse
    
    @POST("stop")
    suspend fun stopSystem(): SystemResponse
    
    @POST("restart")
    suspend fun restartSystem(): SystemResponse
}

// Request models
data class SetRelayRequest(val state: Boolean)
```

### UI Implementation (Jetpack Compose)
```kotlin
@Composable
fun RelayControlPanel(viewModel: RelayViewModel) {
    val relayStates by viewModel.relayStates.observeAsState(emptyMap())
    
    LaunchedEffect(Unit) {
        viewModel.pollAllRelays()
    }
    
    Column(modifier = Modifier.padding(16.dp)) {
        RelayButton(
            relayName = "Ventilation Fan",
            relayId = 1,
            state = relayStates[1] ?: false,
            onToggle = { viewModel.toggleRelay(1) }
        )
        
        RelayButton(
            relayName = "Humidifier",
            relayId = 2,
            state = relayStates[2] ?: false,
            onToggle = { viewModel.toggleRelay(2) }
        )
        
        RelayButton(
            relayName = "LED Strip",
            relayId = 3,
            state = relayStates[3] ?: false,
            onToggle = { viewModel.toggleRelay(3) }
        )
    }
}

@Composable
fun RelayButton(relayName: String, relayId: Int, state: Boolean, onToggle: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(8.dp)
            .clickable { onToggle() },
        backgroundColor = if (state) Color.Green.copy(alpha = 0.3f) else Color.Red.copy(alpha = 0.3f)
    ) {
        Row(
            modifier = Modifier
                .padding(16.dp)
                .fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column {
                Text(relayName, style = MaterialTheme.typography.body1)
                Text("Relay $relayId", style = MaterialTheme.typography.caption)
            }
            
            Button(
                onClick = onToggle,
                colors = ButtonDefaults.buttonColors(
                    backgroundColor = if (state) Color.Green else Color.Gray
                )
            ) {
                Text(if (state) "ON" else "OFF")
            }
        }
    }
}
```

### Error Handling for Relay Control
```kotlin
private fun handleRelayError(relayId: Int, exception: Exception) {
    when (exception) {
        is IOException -> showToast("Network error - check WiFi")
        is HttpException -> {
            when (exception.code()) {
                400 -> showToast("Invalid relay ID: $relayId")
                500 -> showToast("Backend error - relay unavailable")
                else -> showToast("API error: ${exception.code()}")
            }
        }
        else -> showToast("Failed to control relay")
    }
    
    // Optionally: refresh relay state from backend
    getRelayState(relayId)
}
```

---

## System Control Strategy

### Status Dashboard
Display system health on main dashboard:
```kotlin
@Composable
fun SystemStatusBar(viewModel: RelayViewModel) {
    val health by viewModel.systemHealth.observeAsState()
    
    health?.let {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
                .background(
                    color = if (it.status == "ok") Color.Green else Color.Red,
                    shape = RoundedCornerShape(4.dp)
                )
                .padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("Mode: ${it.mode}", color = Color.White)
            Text(
                if (it.backgroundRunning) "Running" else "Stopped",
                color = Color.White,
                fontWeight = FontWeight.Bold
            )
        }
    }
}
```

### Start/Stop/Restart Controls
```kotlin
@Composable
fun SystemControlButtons(viewModel: RelayViewModel) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Button(
            onClick = { viewModel.startSystem() },
            modifier = Modifier.weight(1f)
        ) {
            Text("Start")
        }
        
        Button(
            onClick = { viewModel.stopSystem() },
            modifier = Modifier.weight(1f)
        ) {
            Text("Stop")
        }
        
        Button(
            onClick = { viewModel.restartSystem() },
            modifier = Modifier.weight(1f),
            colors = ButtonDefaults.buttonColors(backgroundColor = Color.Orange)
        ) {
            Text("Restart")
        }
    }
}
```

---

## What to Share with Android Studio Agent

### Option 1: Copy the Entire Instructions File
```bash
# In your Android project root
mkdir -p .github/instructions
cp /path/to/gombabox/.github/instructions/android-app.instructions.md .github/instructions/
```

Then in Android Studio chat, reference:
```
"I have .github/instructions/android-app.instructions.md with full API specs. 
Please use it to implement the relay control and system status features."
```

### Option 2: Paste Specific Sections in Chat
Copy-paste the relevant sections to Android Studio agent:
1. **Relay API Endpoints** - Exact request/response formats
2. **System Status API Endpoints** - Health, start, stop, restart
3. **Relay Control Strategy** - Button layout & Kotlin implementation
4. **System Control Strategy** - Start/stop/restart logic
5. **Retrofit Service Interface** - Ready-to-use interface definition
6. **Data Models** - RelayStatus, SystemHealth, SystemResponse

### Option 3: Reference This Document Directly
Share the document path in chat: 
```
".github/instructions/android-app.instructions.md contains complete API documentation"
```

The agent will:
- ✅ Understand relay IDs and GPIO mappings (1=Fan, 2=Humidifier, 3=LED)
- ✅ Know exact API request/response formats
- ✅ Implement proper Kotlin coroutine patterns
- ✅ Handle errors gracefully
- ✅ Create proper ViewModel state management

---

## Quick Reference: Relay Endpoints

| Operation | Method | Endpoint | Payload | Response |
|-----------|--------|----------|---------|----------|
| Get state | GET | `/api/relay/1` | - | `{"relay_id": 1, "state": true}` |
| Set ON | POST | `/api/relay/1` | `{"state": true}` | `{"relay_id": 1, "state": true}` |
| Set OFF | POST | `/api/relay/1` | `{"state": false}` | `{"relay_id": 1, "state": false}` |

## Quick Reference: System Endpoints

| Operation | Method | Endpoint | Response |
|-----------|--------|----------|----------|
| Health | GET | `/api/health` | `{"status": "ok", "mode": "hardware", "background_running": true}` |
| Start | POST | `/api/start` | `{"status": "started"}` |
| Stop | POST | `/api/stop` | `{"status": "stopped"}` |
| Restart | POST | `/api/restart` | `{"status": "restarting"}` |

---

## Common Integration Patterns

### Polling for Real-Time Updates
```kotlin
// In ViewModel or Activity
fun startAutoRefresh() {
    viewModelScope.launch {
        while (isActive) {
            try {
                // Refresh all relay states
                val states = (1..3).associate { id ->
                    id to apiService.getRelayState(id).state
                }
                _relayStates.value = states
                
                // Refresh system health
                _systemHealth.value = apiService.getHealth()
                
                delay(30000)  // Every 30 seconds
            } catch (e: Exception) {
                logger.error("Refresh error", e)
            }
        }
    }
}
```

### Optimistic UI Update Pattern
```kotlin
fun toggleRelay(relayId: Int) {
    val currentState = _relayStates.value?.get(relayId) ?: false
    
    // Optimistic update (UI responds immediately)
    _relayStates.value = (_relayStates.value ?: emptyMap()).toMutableMap().apply {
        put(relayId, !currentState)
    }
    
    // API call in background
    viewModelScope.launch {
        try {
            val response = apiService.setRelayState(relayId, SetRelayRequest(!currentState))
            // Confirm with backend response
            _relayStates.value = (_relayStates.value ?: emptyMap()).toMutableMap().apply {
                put(relayId, response.state)
            }
        } catch (e: Exception) {
            // Revert on error
            _relayStates.value = (_relayStates.value ?: emptyMap()).toMutableMap().apply {
                put(relayId, currentState)
            }
            showError("Failed to control relay: ${e.message}")
        }
    }
}
```

---

## Testing the API Locally

### Using curl (command line)
```bash
# Get relay state
curl http://192.168.1.100:5000/api/relay/1

# Toggle relay 1 ON
curl -X POST http://192.168.1.100:5000/api/relay/1 \
  -H "Content-Type: application/json" \
  -d '{"state": true}'

# Get system health
curl http://192.168.1.100:5000/api/health

# Start system
curl -X POST http://192.168.1.100:5000/api/start
```

### Using Postman
1. Set up collection for GombaBox API
2. Create requests for each endpoint
3. Use environment variables for base URL
4. Test relay toggle functionality
5. Verify response formats match documentation

---

## Next Steps for Android Development

1. **Copy `.github/instructions/android-app.instructions.md`** to your Android project
2. **Share with Android Studio agent** when implementing:
   - Relay control features (toggles)
   - System status display (health check)
   - System control buttons (start/stop/restart)
3. **Provide agent with:**
   - Full API endpoint documentation (from this file)
   - Kotlin implementation patterns (from this file)
   - Data models (from this file)
4. **Test on real device** connected to Raspberry Pi WiFi
5. **Iterate** based on feedback
