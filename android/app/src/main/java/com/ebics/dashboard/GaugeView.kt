package com.ebics.dashboard

import android.content.Context
import android.graphics.*
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat

class GaugeView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val titlePaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val minMaxPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val arcRect = RectF()
    private var centerX = 0f
    private var centerY = 0f
    private var radius = 0f
    private var strokeWidth = 0f

    var title: String = ""
        set(value) {
            field = value
            invalidate()
        }

    var unit: String = ""
        set(value) {
            field = value
            invalidate()
        }

    var value: Float = 0f
        set(value) {
            field = value
            postInvalidate()
        }

    var minValue: Float = 0f
        set(value) {
            field = value
            postInvalidate()
        }

    var maxValue: Float = 100f
        set(value) {
            field = value
            postInvalidate()
        }

    var currentMin: Float = 0f
        set(value) {
            field = value
            postInvalidate()
        }

    var currentMax: Float = 0f
        set(value) {
            field = value
            postInvalidate()
        }

    var gaugeColor: Int = ContextCompat.getColor(context, R.color.accent_blue)
        set(value) {
            field = value
            invalidate()
        }

    init {
        textPaint.color = ContextCompat.getColor(context, R.color.text_primary)
        textPaint.textSize = 32f
        textPaint.textAlign = Paint.Align.CENTER
        textPaint.typeface = Typeface.DEFAULT_BOLD

        titlePaint.color = ContextCompat.getColor(context, R.color.text_secondary)
        titlePaint.textSize = 14f
        titlePaint.textAlign = Paint.Align.CENTER

        minMaxPaint.color = ContextCompat.getColor(context, R.color.text_secondary)
        minMaxPaint.textSize = 11f
        minMaxPaint.textAlign = Paint.Align.CENTER

        strokeWidth = 12f
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        centerX = w / 2f
        centerY = h / 2f
        radius = (w.coerceAtMost(h) / 2f) - strokeWidth - 10f
        arcRect.set(
            centerX - radius,
            centerY - radius,
            centerX + radius,
            centerY + radius
        )
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        // Draw background arc
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = strokeWidth
        paint.color = ContextCompat.getColor(context, R.color.bg_card)
        paint.strokeCap = Paint.Cap.ROUND
        canvas.drawArc(arcRect, 135f, 270f, false, paint)

        // Draw progress arc
        val progress = ((value - minValue) / (maxValue - minValue)).coerceIn(0f, 1f)
        val sweepAngle = 270f * progress
        paint.color = gaugeColor
        canvas.drawArc(arcRect, 135f, sweepAngle, false, paint)

        // Draw center circle
        paint.style = Paint.Style.FILL
        paint.color = ContextCompat.getColor(context, R.color.bg_card)
        canvas.drawCircle(centerX, centerY, radius - strokeWidth - 5f, paint)

        // Draw value text
        textPaint.color = ContextCompat.getColor(context, R.color.text_primary)
        val valueText = String.format("%.1f", value)
        canvas.drawText(valueText, centerX, centerY + 10f, textPaint)

        // Draw unit
        textPaint.textSize = 14f
        textPaint.color = ContextCompat.getColor(context, R.color.text_secondary)
        canvas.drawText(unit, centerX, centerY + 30f, textPaint)
        textPaint.textSize = 32f

        // Draw title
        canvas.drawText(title, centerX, centerY + radius + 30f, titlePaint)

        // Draw min/max
        val minText = String.format("%.0f", minValue)
        val maxText = String.format("%.0f", maxValue)
        canvas.drawText(minText, centerX - radius + 15f, centerY + radius + 15f, minMaxPaint)
        canvas.drawText(maxText, centerX + radius - 15f, centerY + radius + 15f, minMaxPaint)

        // Draw current min/max if available
        if (currentMin != 0f || currentMax != 0f) {
            minMaxPaint.textSize = 9f
            val rangeText = String.format("[%.0f-%.0f]", currentMin, currentMax)
            canvas.drawText(rangeText, centerX, centerY + radius + 45f, minMaxPaint)
            minMaxPaint.textSize = 11f
        }
    }
}