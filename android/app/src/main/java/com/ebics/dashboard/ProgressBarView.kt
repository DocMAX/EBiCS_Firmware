package com.ebics.dashboard

import android.content.Context
import android.graphics.*
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat

class ProgressBarView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val backgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val progressPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val titlePaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val valuePaint = Paint(Paint.ANTI_ALIAS_FLAG)

    var title: String = ""
        set(value) {
            field = value
            invalidate()
        }

    var value: Float = 0f
        set(value) {
            field = value
            postInvalidate()
        }

    var maxValue: Float = 100f
        set(value) {
            field = value
            postInvalidate()
        }

    var unit: String = ""
        set(value) {
            field = value
            postInvalidate()
        }

    var progressColor: Int = ContextCompat.getColor(context, R.color.accent_green)
        set(value) {
            field = value
            postInvalidate()
        }

    init {
        backgroundPaint.color = ContextCompat.getColor(context, R.color.bg_card)
        backgroundPaint.style = Paint.Style.FILL

        progressPaint.style = Paint.Style.FILL

        textPaint.color = ContextCompat.getColor(context, R.color.text_primary)
        textPaint.textSize = 28f
        textPaint.textAlign = Paint.Align.CENTER
        textPaint.typeface = Typeface.DEFAULT_BOLD

        titlePaint.color = ContextCompat.getColor(context, R.color.text_secondary)
        titlePaint.textSize = 12f
        titlePaint.textAlign = Paint.Align.CENTER

        valuePaint.color = ContextCompat.getColor(context, R.color.text_primary)
        valuePaint.textSize = 14f
        valuePaint.textAlign = Paint.Align.CENTER
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val padding = 8f
        val cornerRadius = 8f
        val barHeight = 32f
        val titleY = 20f
        val barTop = 30f
        val barBottom = barTop + barHeight
        val valueY = barBottom + 20f

        // Draw title
        canvas.drawText(title, width / 2f, titleY, titlePaint)

        // Draw background
        val bgRect = RectF(padding, barTop, width - padding, barBottom)
        canvas.drawRoundRect(bgRect, cornerRadius, cornerRadius, backgroundPaint)

        // Draw progress
        val progress = (value / maxValue).coerceIn(0f, 1f)
        val progressWidth = (width - 2 * padding) * progress
        val progressRect = RectF(padding, barTop, padding + progressWidth, barBottom)
        progressPaint.color = progressColor
        canvas.drawRoundRect(progressRect, cornerRadius, cornerRadius, progressPaint)

        // Draw value text
        val valueText = String.format("%.1f %s", value, unit)
        canvas.drawText(valueText, width / 2f, valueY, textPaint)
    }
}