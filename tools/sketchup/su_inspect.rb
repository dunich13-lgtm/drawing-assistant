# Read-only inspection of the open SketchUp model. Changes nothing. All output in metres.
#   SuInspect.summary                 -> short text: model, units, tags, top-level groups
#   SuInspect.elements                -> data/sketchup_elements.json (groups/components under the selection, or whole model)
#   SuInspect.tag('My tag')           -> text: every instance on a tag, with world bounds and face stats
#   SuInspect.selection               -> data/sketchup_selection.json (what the user selected)
#   SuInspect.selection_faces         -> data/sketchup_selection_faces.json (every face in the selection)
#   SuInspect.probe_down(x, y, z_from = 50, skip = nil) -> surfaces hit straight down from (x, y, z_from)
require 'json'
require 'fileutils'

module SuInspect
  ROOT = defined?(SuBridge) ? SuBridge::ROOT : File.expand_path('../..', File.dirname(__FILE__))
  MAX_ITEMS = 60_000
  MAX_FACES = 20_000

  def self.m(v) (v.to_f * 0.0254).round(4) end
  def self.pt(p) [m(p.x), m(p.y), m(p.z)] end
  def self.inst?(e) e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance) end
  def self.name_of(e) e.name.to_s.empty? ? e.definition.name.to_s : e.name.to_s end

  def self.write(name, obj)
    FileUtils.mkdir_p(File.join(ROOT, 'data'))
    out = File.join(ROOT, 'data', name)
    File.open(out, 'w:UTF-8') { |f| f.write(JSON.pretty_generate(obj)) }
    out
  end

  def self.world_box(defn, tr)
    bb = defn.bounds
    return nil if bb.empty?
    pts = (0..7).map { |i| bb.corner(i).transform(tr) }
    [[m(pts.map(&:x).min), m(pts.map(&:y).min), m(pts.map(&:z).min)],
     [m(pts.map(&:x).max), m(pts.map(&:y).max), m(pts.map(&:z).max)]]
  end

  def self.summary
    mo = Sketchup.active_model
    u = mo.options['UnitsOptions']['LengthUnit'] rescue '?'
    tops = mo.entities.select { |e| inst?(e) }.map { |e| "#{name_of(e)} [#{e.layer.name}]" }
    ["model: #{mo.title.empty? ? '(untitled)' : mo.title}  path: #{mo.path}",
     "sketchup #{Sketchup.version}, length unit code #{u}",
     "tags (#{mo.layers.size}): #{mo.layers.map(&:name).first(40).join(', ')}",
     "top-level groups/components (#{tops.size}): #{tops.first(40).join('; ')}",
     "loose faces at top level: #{mo.entities.grep(Sketchup::Face).size}"].join("\n")
  end

  def self.walk(entities, tr, path, rows)
    entities.each do |e|
      break if rows.size >= MAX_ITEMS
      next unless inst?(e)
      t = tr * e.transformation
      rows << { 'path' => (path + [name_of(e)]).join(' / '), 'depth' => path.size, 'name' => name_of(e),
                'tag' => e.layer&.name, 'faces' => e.definition.entities.grep(Sketchup::Face).size,
                'box' => world_box(e.definition, t) }
      walk(e.definition.entities, t, path + [name_of(e)], rows)
    end
  end

  def self.elements
    mo = Sketchup.active_model
    rows = []
    sel = mo.selection.to_a.select { |e| inst?(e) }
    if sel.empty?
      walk(mo.entities, Geom::Transformation.new, [], rows)
    else
      sel.each do |e|
        rows << { 'path' => name_of(e), 'depth' => 0, 'name' => name_of(e), 'tag' => e.layer&.name,
                  'faces' => e.definition.entities.grep(Sketchup::Face).size, 'box' => world_box(e.definition, e.transformation) }
        walk(e.definition.entities, e.transformation, [name_of(e)], rows)
      end
    end
    out = write('sketchup_elements.json', 'exported_at' => Time.now.to_s, 'elements' => rows, 'truncated' => rows.size >= MAX_ITEMS)
    "#{rows.size} elements -> #{out}"
  end

  def self.tag(tag_name, max_depth = 8)
    mo = Sketchup.active_model
    out = []
    stack = [[mo.entities, Geom::Transformation.new, []]]
    until stack.empty?
      ents, tr, path = stack.pop
      ents.each do |e|
        next unless inst?(e)
        t = tr * e.transformation
        nm = name_of(e)
        if e.layer.name == tag_name
          bb = Geom::BoundingBox.new
          c = e.definition.bounds
          (0..7).each { |i| bb.add(c.corner(i).transform(t)) }
          fs = e.definition.entities.grep(Sketchup::Face)
          out << "#{(path.last(2) + [nm]).join(' / ')} | x #{bb.min.x.to_m.round(2)}..#{bb.max.x.to_m.round(2)} " \
                 "y #{bb.min.y.to_m.round(2)}..#{bb.max.y.to_m.round(2)} z #{bb.min.z.to_m.round(3)}..#{bb.max.z.to_m.round(3)} " \
                 "| faces #{fs.size} holes #{fs.sum { |f| f.loops.size - 1 }} mat #{e.material&.display_name}"
          next
        end
        stack << [e.definition.entities, t, path + [nm]] if path.size < max_depth
      end
    end
    out.empty? ? "nothing on tag '#{tag_name}'" : out.join("\n")
  end

  def self.world_bounds(e, tr)
    bb = Geom::BoundingBox.new
    if inst?(e)
      t = tr * e.transformation
      e.definition.entities.each do |c|
        if c.respond_to?(:vertices) then c.vertices.each { |v| bb.add(v.position.transform(t)) }
        elsif inst?(c) then (sub = world_bounds(c, t); bb.add(sub) unless sub.empty?)
        end
      end
    elsif e.respond_to?(:vertices)
      e.vertices.each { |v| bb.add(v.position.transform(tr)) }
    end
    bb
  end

  # Inside an open group SketchUp already reports the active context in world coordinates: use identity.
  def self.selection
    tr = Geom::Transformation.new
    rows = Sketchup.active_model.selection.map do |e|
      bb = world_bounds(e, tr)
      row = { 'type' => e.typename, 'name' => (e.respond_to?(:name) ? e.name.to_s : ''),
              'definition' => (e.respond_to?(:definition) ? e.definition.name.to_s : nil),
              'tag' => (e.respond_to?(:layer) && e.layer ? e.layer.name : nil),
              'bounds_min_m' => (bb.empty? ? nil : pt(bb.min)), 'bounds_max_m' => (bb.empty? ? nil : pt(bb.max)) }
      row['vertices_m'] = e.vertices.map { |v| pt(v.position) } if e.is_a?(Sketchup::Edge)
      row
    end
    out = write('sketchup_selection.json', 'exported_at' => Time.now.to_s, 'selection' => rows)
    "#{rows.size} selected item(s) -> #{out}"
  end

  def self.mat_info(mat)
    return nil unless mat
    c = mat.color
    { 'name' => mat.display_name, 'rgb' => [c.red, c.green, c.blue],
      'texture' => (mat.texture ? File.basename(mat.texture.filename.to_s) : nil) }
  end

  def self.collect_faces(entities, tr, path, inherited, faces)
    entities.each do |e|
      break if faces.size >= MAX_FACES
      if e.is_a?(Sketchup::Face)
        faces << { 'path' => path, 'tag' => e.layer&.name, 'material' => mat_info(e.material || inherited),
                   'normal' => e.normal.transform(tr).normalize.to_a.map { |v| v.round(5) },
                   'area_m2' => (e.area * 0.00064516).round(5),
                   'vertices_m' => e.outer_loop.vertices.map { |v| pt(v.position.transform(tr)) } }
      elsif inst?(e)
        collect_faces(e.definition.entities, tr * e.transformation, path + [name_of(e)], e.material || inherited, faces)
      end
    end
  end

  def self.selection_faces
    faces = []
    Sketchup.active_model.selection.each do |e|
      if e.is_a?(Sketchup::Face) then collect_faces([e], Geom::Transformation.new, [], nil, faces)
      elsif inst?(e) then collect_faces(e.definition.entities, e.transformation, [name_of(e)], e.material, faces)
      end
    end
    out = write('sketchup_selection_faces.json', 'exported_at' => Time.now.to_s, 'faces' => faces, 'truncated' => faces.size >= MAX_FACES)
    "#{faces.size} faces -> #{out}"
  end

  # Surfaces straight below a point. Returns [[z_m, normal_z, element_name], ...] from top to bottom.
  # A raytest hits faces from both sides; a normal_z > 0.5 is an up-facing surface (floor), < -0.5 a ceiling.
  # skip: regex on element/tag names to ignore (e.g. the builder's own group).
  def self.probe_down(x, y, z_from = 50, skip = nil, max_hits = 40)
    mo = Sketchup.active_model
    p = Geom::Point3d.new(x.m, y.m, z_from.m)
    hits = []
    max_hits.times do
      r = mo.raytest([p, Z_AXIS.reverse], true)
      break unless r
      path = r[1]
      ignore = skip && path.any? { |e| (e.respond_to?(:name) && e.name.to_s =~ skip) || (e.respond_to?(:layer) && e.layer.name =~ skip) }
      unless ignore
        tr = Geom::Transformation.new
        path[0..-2].each { |e| tr *= e.transformation if e.respond_to?(:transformation) }
        f = path.last
        n = f.is_a?(Sketchup::Face) ? f.normal.transform(tr).normalize : Z_AXIS
        holder = path[0..-2].last
        hits << [r[0].z.to_m.round(4), n.z.round(3), holder && inst?(holder) ? name_of(holder) : '(model)']
      end
      p = r[0].offset(Z_AXIS.reverse, 0.0005.m)
    end
    hits
  end
end
