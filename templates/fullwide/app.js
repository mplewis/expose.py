// https://github.com/ryanve/res/blob/master/src/index.js
function pixelRatio() {
  if (typeof window == 'undefined') return 0
  return (+window.devicePixelRatio ||
          Math.sqrt(screen.deviceXDPI*screen.deviceYDPI)/one.dpi ||
          0)
}

function browserWidth() {
  return (window.innerWidth ||
          document.documentElement.clientWidth ||
          document.body.clientWidth)
}

function trueWidth() {
  return browserWidth() * pixelRatio()
}

function scrolledTo(pos) {
  var progress = document.getElementById('progress-inner')
  var total = slides.length
  var width = pos * 100 / total + '%'
  progress.style.width = width
}

slides.forEach(function(id, i) {
  var elem = document.getElementById(id)
  if (!elem) return
  
  var watcher = scrollMonitor.create(elem)
  watcher.enterViewport(function() {
    scrolledTo(i + 1)
  })
})

document.addEventListener('lazybeforeunveil', function(e) {
  // Lazy load responsive videos right before they're unveiled by lazysizes
  // This doesn't load larger versions when the window resizes
  var elem = e.target
  // the _content div is lazy loaded but we need the original slide id
  // to look up the source content
  var id = elem.id.replace('_content', '')
  var sources = videoSources[id]
  if (!sources) return  // no video sources = not a video

  // Get all video widths, unique them, and sort descending
  var widths = (_.uniq(sources.map(function(s) { return s[0] }))
                .sort(function(a, b) { return b - a }))
  // default to smallest width in case we're on a really tiny screen
  var width = widths[widths.length - 1]
  // use some to short-circuit: http://stackoverflow.com/a/2641374/254187
  widths.some(function(w) {
    if (w < trueWidth()) {
      width = w
      return true
    }
    return false
  })

  // at this point, width is the preferred video width for this screen
  // select videos with that width and present them
  var toPresent = (sources
                   .filter(function(pair) { return pair[0] === width })
                   .map(function(pair) { return pair[1] }))

  var html = ''
  toPresent.forEach(function(src) {
    html += '<source src="' + src + '">'
  })
  elem.innerHTML = html

  // add poster image while video loads
  var poster = toPresent[0].split('.')[0] + '.jpg'
  elem.setAttribute('poster', poster)

})

// Request metadata and add it to the description elements
reqwest('metadata.yml').then(function(resp) {
  var metadata = jsyaml.safeLoad(resp.responseText)
  _.forOwn(metadata.slides, function(val, key) {
    var id = slidesById[key] + '_desc'
    var elem = document.getElementById(id)
    var content = val.content
    var style = val.style
    if (content) elem.innerHTML = markdown.toHTML(content)
    if (style) elem.style.cssText = style
  })
})

scrolledTo(1)

$('.slide-desc').flowtype({
  minFont: 12,
  maxFont: 32
})
