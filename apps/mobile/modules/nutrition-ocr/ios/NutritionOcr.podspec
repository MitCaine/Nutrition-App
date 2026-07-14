Pod::Spec.new do |s|
  s.name           = 'NutritionOcr'
  s.version        = '0.1.0'
  s.summary        = 'On-device Apple Vision OCR bridge for Nutrition App diagnostics.'
  s.description    = 'A narrow Expo module that recognizes text in local still images.'
  s.license        = { :type => 'MIT' }
  s.author         = 'Nutrition App'
  s.homepage       = 'https://example.invalid/nutrition-ocr'
  s.platforms      = { :ios => '15.1' }
  s.swift_version  = '5.4'
  s.source         = { :path => '.' }
  s.static_framework = true
  s.source_files   = '**/*.swift'

  s.dependency 'ExpoModulesCore'
  s.frameworks = 'Vision', 'ImageIO'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }
end
