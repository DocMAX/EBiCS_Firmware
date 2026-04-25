package com.ebics.dashboard

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.Socket
import java.util.concurrent.Executors
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "EBiCS_Dashboard"
        private const val ESP_HOST = "esp32-mougg.lan"
        private const val ESP_PORT = 1003
    }

    // UI Components
    private lateinit var connectionStatus: TextView
    private lateinit var tvAssistLevel: TextView
    private lateinit var tvPasPulses: TextView
    private lateinit var tvSpeedPulses: TextView

    // Gauges
    private lateinit var gaugeThrottle: GaugeView
    private lateinit var gaugeTorque: GaugeView
    private lateinit var gaugeBrake: GaugeView
    private lateinit var gaugeCadence: GaugeView
    private lateinit var gaugeVoltage: GaugeView
    private lateinit var gaugeSpeed: GaugeView

    // Progress Bars
    private lateinit var barThrottle: ProgressBarView
    private lateinit var barTorque: ProgressBarView
    private lateinit var barAssist: ProgressBarView

    // Buttons
    private lateinit var btnAssist0: Button
    private lateinit var btnAssist1: Button
    private lateinit var btnAssist2: Button
    private lateinit var btnAssist3: Button
    private lateinit var btnReset: Button

    // Data
    private var currentAssistLevel = 0
    private var firmwareAssistLevel = 0
    private var pasPulseCount = 0
    private var speedPulseCount = 0

    private val minVals = mutableMapOf<String, Float>()
    private val maxVals = mutableMapOf<String, Float>()

    // Network
    private var socket: Socket? = null
    private var writer: PrintWriter? = null
    private var reader: BufferedReader? = null
    private var connected = false

    private val mainHandler = Handler(Looper.getMainLooper())
    private val ioExecutor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        setupViews()
        setupButtons()
        connectToESP32()
    }

    private fun setupViews() {
        connectionStatus = findViewById(R.id.connectionStatus)
        tvAssistLevel = findViewById(R.id.tvAssistLevel)
        tvPasPulses = findViewById(R.id.tvPasPulses)
        tvSpeedPulses = findViewById(R.id.tvSpeedPulses)

        gaugeThrottle = findViewById(R.id.gaugeThrottle)
        gaugeThrottle.title = getString(R.string.label_throttle)
        gaugeThrottle.unit = "V"
        gaugeThrottle.minValue = 0f
        gaugeThrottle.maxValue = 5f

        gaugeTorque = findViewById(R.id.gaugeTorque)
        gaugeTorque.title = getString(R.string.label_torque)
        gaugeTorque.unit = "V"
        gaugeTorque.minValue = 0f
        gaugeTorque.maxValue = 5f
        gaugeTorque.gaugeColor = ContextCompat.getColor(this, R.color.accent_orange)

        gaugeBrake = findViewById(R.id.gaugeBrake)
        gaugeBrake.title = getString(R.string.label_brake)
        gaugeBrake.unit = "V"
        gaugeBrake.minValue = 0f
        gaugeBrake.maxValue = 5f
        gaugeBrake.gaugeColor = ContextCompat.getColor(this, R.color.accent_red)

        gaugeCadence = findViewById(R.id.gaugeCadence)
        gaugeCadence.title = getString(R.string.label_cadence)
        gaugeCadence.unit = "RPM"
        gaugeCadence.minValue = 0f
        gaugeCadence.maxValue = 120f
        gaugeCadence.gaugeColor = ContextCompat.getColor(this, R.color.accent_green)

        gaugeVoltage = findViewById(R.id.gaugeVoltage)
        gaugeVoltage.title = getString(R.string.label_voltage)
        gaugeVoltage.unit = "V"
        gaugeVoltage.minValue = 20f
        gaugeVoltage.maxValue = 60f
        gaugeVoltage.gaugeColor = ContextCompat.getColor(this, R.color.accent_yellow)

        gaugeSpeed = findViewById(R.id.gaugeSpeed)
        gaugeSpeed.title = getString(R.string.label_speed)
        gaugeSpeed.unit = "km/h"
        gaugeSpeed.minValue = 0f
        gaugeSpeed.maxValue = 100f
        gaugeSpeed.gaugeColor = ContextCompat.getColor(this, R.color.accent_blue)

        barThrottle = findViewById(R.id.barThrottle)
        barThrottle.title = getString(R.string.label_throttle)
        barThrottle.unit = "V"
        barThrottle.maxValue = 5f
        barThrottle.progressColor = ContextCompat.getColor(this, R.color.accent_orange)

        barTorque = findViewById(R.id.barTorque)
        barTorque.title = getString(R.string.label_torque)
        barTorque.unit = "V"
        barTorque.maxValue = 5f
        barTorque.progressColor = ContextCompat.getColor(this, R.color.accent_yellow)

        barAssist = findViewById(R.id.barAssist)
        barAssist.title = getString(R.string.label_assist)
        barAssist.unit = ""
        barAssist.maxValue = 3f
        barAssist.progressColor = ContextCompat.getColor(this, R.color.accent_green)
    }

    private fun setupButtons() {
        btnAssist0 = findViewById(R.id.btnAssist0)
        btnAssist1 = findViewById(R.id.btnAssist1)
        btnAssist2 = findViewById(R.id.btnAssist2)
        btnAssist3 = findViewById(R.id.btnAssist3)
        btnReset = findViewById(R.id.btnReset)

        btnAssist0.setOnClickListener { sendAssistLevel(0) }
        btnAssist1.setOnClickListener { sendAssistLevel(1) }
        btnAssist2.setOnClickListener { sendAssistLevel(2) }
        btnAssist3.setOnClickListener { sendAssistLevel(3) }
        btnReset.setOnClickListener { resetCounters() }
    }

    private fun connectToESP32() {
        updateConnectionStatus(R.string.connecting, false)
        ioExecutor.execute {
            try {
                Log.d(TAG, "Connecting to $ESP_HOST:$ESP_PORT")
                socket = Socket()
                socket!!.connect(java.net.InetSocketAddress(ESP_HOST, ESP_PORT), 5000)
                socket!!.keepAlive = true
                socket!!.tcpNoDelay = true
                writer = PrintWriter(socket!!.getOutputStream(), true)
                reader = BufferedReader(InputStreamReader(socket!!.getInputStream()))
                connected = true
                mainHandler.post {
                    updateConnectionStatus(R.string.connected, true)
                    Toast.makeText(this, "Connected to ESP32", Toast.LENGTH_SHORT).show()
                }
                Log.d(TAG, "Connection established, starting reader thread")
                startReading()
            } catch (e: Exception) {
                Log.e(TAG, "Connection failed", e)
                connected = false
                mainHandler.post {
                    updateConnectionStatus(R.string.disconnected, false)
                    Toast.makeText(this, "Connection failed: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun startReading() {
        thread {
            try {
                while (connected) {
                    val line = reader?.readLine()
                    if (line != null) {
                        Log.d(TAG, "Received line: $line")
                        processLine(line)
                    } else {
                        Log.w(TAG, "EOF reached, connection closed by server")
                        break
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Read error", e)
                if (connected) {
                    mainHandler.post {
                        connected = false
                        updateConnectionStatus(R.string.disconnected, false)
                        Toast.makeText(this, "Connection lost: ${e.message}", Toast.LENGTH_LONG).show()
                    }
                }
            }
        }
    }

    private fun processLine(line: String) {
        var cleanLine = line.trim()
        if (cleanLine.startsWith("TX: ")) {
            cleanLine = cleanLine.substring(4)
        }
        if (cleanLine.startsWith("RX: ")) {
            return
        }
        if (cleanLine.isEmpty()) {
            return
        }
        parseDataLine(cleanLine)
    }

    private fun parseDataLine(line: String) {
        val trimmedLine = line.trim()
        Log.d(TAG, "Parsing line: '$trimmedLine'")
        val parts = trimmedLine.split(",").map { it.trim() }
        Log.d(TAG, "Parts count: ${parts.size}")
        if (parts.size != 30) {
            Log.d(TAG, "Invalid line: $trimmedLine (${parts.size} fields)")
            return
        }

        try {
            val row = parts.map { it.toInt() }
            Log.d(TAG, "Parsed row successfully")

            // Raw values
            val rawVoltage = row[0]
            val rawThrottle = row[1]
            val rawCurrent1 = row[2]
            val rawCurrent2 = row[3]
            val rawCurrent3 = row[4]
            val rawBrakeAdc = row[5]
            val rawTorque = row[6]
            val rawTemperature = row[7]

            // GPIO
            val hall1 = row[8]
            val hall2 = row[9]
            val hall3 = row[10]
            val brake = row[11]
            val pas = row[12]
            val speed = row[13]
            val led = row[14]
            val light = row[15]
            val brakeLight = row[16]
            firmwareAssistLevel = row[17]

            // Parameters
            val speedKmhX100 = row[18]
            val p17 = row[19]
            val p18 = row[20]
            val p19 = row[21]
            val p03 = row[22]
            val p06 = row[23]
            val p07 = row[24]
            val p08 = row[25]
            val p11 = row[26]
            val p12 = row[27]
            val p13 = row[28]
            val p14 = row[29]

            // Conversions
            val throttle = rawThrottle / 1000.0f
            val torque = rawTorque / 1000.0f
            val brakeAdc = rawBrakeAdc / 1000.0f
            val voltage = rawVoltage / 40.26f
            val speedKmh = speedKmhX100 / 100.0f

            // Update min/max
            updateMinMax("throttle", throttle)
            updateMinMax("torque", torque)
            updateMinMax("voltage", voltage)
            updateMinMax("speed", speedKmh)
            updateMinMax("raw_throttle", rawThrottle.toFloat())
            updateMinMax("raw_torque", rawTorque.toFloat())
            updateMinMax("raw_voltage", rawVoltage.toFloat())

            // PAS period calculation (simplified)
            val pasPeriod = if (pas == 1) 50 else 3000
            val cadence = if (pasPeriod < 3000) (60000f / pasPeriod / 32).toInt() else 0

            // Update UI
            Log.d(TAG, "Calling updateUI with throttle=$throttle, cadence=$cadence")
            mainHandler.post {
                updateUI(
                    throttle, torque, brakeAdc, cadence, voltage,
                    hall1 or (hall2 shl 1) or (hall3 shl 2),
                    brake, pas, speed, led, light, brakeLight,
                    rawVoltage, rawThrottle, rawCurrent1, rawCurrent2, rawCurrent3,
                    rawBrakeAdc, rawTorque, rawTemperature, pasPeriod,
                    firmwareAssistLevel, speedKmh, p17, p18, p19, p03, p06, p07, p08, p11, p12, p13, p14
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "Parse error: ${e.message}", e)
        }
    }

    private fun updateMinMax(name: String, value: Float) {
        if (name !in minVals || value < minVals[name]!!) {
            minVals[name] = value
        }
        if (name !in maxVals || value > maxVals[name]!!) {
            maxVals[name] = value
        }
    }

    private fun updateUI(
        throttle: Float, torque: Float, brakeAdc: Float, cadence: Int,
        voltage: Float, hallstate: Int, brake: Int, pas: Int, speed: Int,
        led: Int, light: Int, brakeLight: Int, rawVoltage: Int, rawThrottle: Int,
        rawCurrent1: Int, rawCurrent2: Int, rawCurrent3: Int, rawBrakeAdc: Int,
        rawTorque: Int, rawTemperature: Int, pasPeriod: Int,
        firmwareAssist: Int, speedKmh: Float, p17: Int, p18: Int, p19: Int,
        p03: Int, p06: Int, p07: Int, p08: Int, p11: Int, p12: Int, p13: Int, p14: Int
    ) {
        Log.d(TAG, "updateUI called: throttle=$throttle, cadence=$cadence, speed=$speedKmh")
        // Gauges
        gaugeThrottle.value = throttle
        gaugeThrottle.currentMin = minVals["throttle"] ?: 0f
        gaugeThrottle.currentMax = maxVals["throttle"] ?: 0f

        gaugeTorque.value = torque
        gaugeTorque.currentMin = minVals["torque"] ?: 0f
        gaugeTorque.currentMax = maxVals["torque"] ?: 0f

        gaugeBrake.value = brakeAdc

        gaugeCadence.value = cadence.toFloat()

        gaugeVoltage.value = voltage
        gaugeVoltage.currentMin = minVals["voltage"] ?: 0f
        gaugeVoltage.currentMax = maxVals["voltage"] ?: 0f

        gaugeSpeed.value = speedKmh
        gaugeSpeed.currentMin = minVals["speed"] ?: 0f
        gaugeSpeed.currentMax = maxVals["speed"] ?: 0f

        // Progress bars
        barThrottle.value = throttle
        barTorque.value = torque
        barAssist.value = firmwareAssist.toFloat()

        // Text views
        tvAssistLevel.text = "Assist: $firmwareAssist (Local: $currentAssistLevel)"
        tvPasPulses.text = "PAS: $pasPulseCount"
        tvSpeedPulses.text = "Speed: $speedPulseCount"
    }

    private fun sendAssistLevel(level: Int) {
        currentAssistLevel = level
        tvAssistLevel.text = "Assist: $firmwareAssistLevel (Local: $currentAssistLevel)"

        // Highlight selected button
        btnAssist0.setBackgroundColor(if (level == 0) 0xFF4CAF50.toInt() else 0xFF333333.toInt())
        btnAssist1.setBackgroundColor(if (level == 1) 0xFF4CAF50.toInt() else 0xFF333333.toInt())
        btnAssist2.setBackgroundColor(if (level == 2) 0xFF4CAF50.toInt() else 0xFF333333.toInt())
        btnAssist3.setBackgroundColor(if (level == 3) 0xFF4CAF50.toInt() else 0xFF333333.toInt())

        if (connected) {
            ioExecutor.execute {
                try {
                    writer?.println(level.toString())
                } catch (e: Exception) {
                    Log.e(TAG, "Send error", e)
                }
            }
        }
    }

    private fun resetCounters() {
        pasPulseCount = 0
        speedPulseCount = 0
        minVals.clear()
        maxVals.clear()
        tvPasPulses.text = "PAS: 0"
        tvSpeedPulses.text = "Speed: 0"
        Toast.makeText(this, "Counters reset", Toast.LENGTH_SHORT).show()
    }

    private fun updateConnectionStatus(resId: Int, isConnected: Boolean) {
        connectionStatus.text = getString(resId)
        connectionStatus.setTextColor(
            ContextCompat.getColor(this, if (isConnected) R.color.accent_green else R.color.accent_red)
        )
    }

    override fun onDestroy() {
        super.onDestroy()
        connected = false
        ioExecutor.shutdown()
        try {
            socket?.close()
        } catch (e: Exception) {
            Log.e(TAG, "Close error", e)
        }
    }
}