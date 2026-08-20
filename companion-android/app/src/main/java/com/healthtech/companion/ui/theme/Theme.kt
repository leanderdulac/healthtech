package com.healthtech.companion.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Sky = Color(0xFF0EA5E9)
private val SkyBright = Color(0xFF38BDF8)
private val Bg = Color(0xFF080A0F)
private val Surface = Color(0xFF111827)
private val OnBg = Color(0xFFE2E8F0)
private val Muted = Color(0xFF94A3B8)
private val Ok = Color(0xFF34D399)
private val Err = Color(0xFFEF4444)

private val DarkColors = darkColorScheme(
    primary = Sky,
    onPrimary = Color.White,
    secondary = SkyBright,
    background = Bg,
    onBackground = OnBg,
    surface = Surface,
    onSurface = OnBg,
    surfaceVariant = Color(0xFF1E293B),
    onSurfaceVariant = Muted,
    error = Err,
    onError = Color.White,
    tertiary = Ok,
)

@Composable
fun HealthtechTheme(content: @Composable () -> Unit) {
    // Dark fixo — alinhado ao dashboard web
    MaterialTheme(
        colorScheme = DarkColors,
        content = content,
    )
}
