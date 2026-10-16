/* Local Three.js face rig. Phoneme weights deform authored mouth shapes;
 * teeth, tongue and the wire overlay share those same weights.
 */
(() => {
  "use strict";
  const baseURL = document.currentScript.src;
  const assetURL = new URL("assets/mesh-face/mpfb.glb", baseURL);
  const POSES = [
    "Rest", "M / B / P", "F / V", "TH", "T / D", "K / G", "CH / SH / J", "S / Z",
    "N / L", "R", "A / AH", "E / EH", "I / EE", "O / OH", "U / OO", "Blink",
    "Listening", "Thinking", "Curious", "Smiling", "Laughing", "Surprised", "Concerned", "Reassuring",
  ];
  const VISEMES = [null, "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U"];
  const GAIN = [0, 1, .85, .7, .8, .7, .8, .7, .7, .8, .65, .65, .65, .8, .85];
  const STATE_POSE = { idle: 0, listening: 16, thinking: 17, error: 22, smiling: 19, curious: 18, reassuring: 23 };

  class MeshAvatar {
    static poses = POSES;
    constructor(onError) {
      this.onError = onError;
      this.ready = false;
      this.loading = null;
      this.pose = 0;
      this.targets = [];
      this.appearance = "portrait";
      this.nextBlink = 4000;
      this.blinkAt = null;
      this.reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
      this.motion = new AvatarMotion();
    }

    resetMouth() {
      this.pose = 0;
      for (const mesh of this.targets) mesh.morphTargetInfluences.fill(0);
    }

    load() {
      if (this.loading) return this.loading;
      this.loading = this.prepare().then(() => { this.ready = true; return true; }).catch(error => {
        console.warn("Face rig unavailable:", error);
        this.dispose();
        this.loading = null;
        this.ready = false;
        this.onError?.();
        return false;
      });
      return this.loading;
    }

    async prepare() {
      this.dispose();
      const THREE = await import("three");
      const { GLTFLoader } = await import(new URL("vendor/three/loaders/GLTFLoader.js", baseURL));
      const gltf = await new GLTFLoader().loadAsync(assetURL.href);
      this.THREE = THREE;
      this.scene = new THREE.Scene();
      this.scene.background = new THREE.Color(0x050907);
      this.model = gltf.scene;
      this.scene.add(this.model);
      this.camera = new THREE.OrthographicCamera(-.2, .2, .2, -.2, .01, 10);
      this.camera.position.set(0, 1.635, 1.5);
      this.camera.lookAt(0, 1.635, 0);
      this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
      this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
      this.renderer.localClippingEnabled = true;
      this.renderer.domElement.addEventListener("webglcontextlost", event => {
        event.preventDefault();
        this.ready = false;
        this.loading = null;
        this.onError?.();
      });
      this.scene.add(new THREE.HemisphereLight(0xa6ffcd, 0x06140e, 2));
      const key = new THREE.DirectionalLight(0xd5ffe8, 3);
      key.position.set(-1, 2, 3);
      this.scene.add(key);
      const rim = new THREE.DirectionalLight(0x50ffb0, 2);
      rim.position.set(1, 1.8, -.5);
      this.scene.add(rim);
      // Hide the unused body below the neck; camera fitting includes the hair.
      const clippingPlanes = [new THREE.Plane(new THREE.Vector3(0, 1, 0), -1.44)];
      const meshes = [];
      this.model.traverse(node => { if (node.isMesh) meshes.push(node); });
      this.targets = [];
      for (const mesh of meshes) {
        if (mesh.morphTargetInfluences) this.targets.push(mesh);
        mesh.frustumCulled = false;
        const name = mesh.name.toLowerCase();
        if (name.includes("casualsuit")) { mesh.visible = false; continue; }
        const eyes = name.includes("high-poly"), hair = name.includes("ponytail");
        const detail = name.includes("eyebrow") || name.includes("eyelash");
        const teeth = name.includes("teeth"), tongue = name.includes("tongue");
        if (eyes || detail || hair) {
          mesh.material = mesh.material.clone();
          mesh.material.color.set(eyes ? 0xb1ebca : hair ? 0x26774c : 0x215339);
          mesh.material.roughness = .8;
          mesh.material.clippingPlanes = clippingPlanes;
        } else {
          mesh.material = new THREE.MeshStandardMaterial({
            color: teeth ? 0x91b99c : tongue ? 0x193c29 : 0x125336,
            roughness: .64, metalness: .1, clippingPlanes,
            polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
          });
        }
        if (!eyes && !detail && !teeth && !tongue && !hair) {
          const wire = mesh.clone(false);
          wire.name = mesh.name + "_wire";
          wire.material = new THREE.MeshBasicMaterial({ color: 0x45be7e, wireframe: true,
            transparent: true, opacity: .085, depthWrite: false, clippingPlanes });
          wire.morphTargetInfluences = mesh.morphTargetInfluences;
          wire.frustumCulled = false;
          mesh.parent.add(wire);
        }
      }
      this.head = this.model.getObjectByName("Head");
      this.headRest = this.head?.quaternion.clone();
      this.neck = this.model.getObjectByName("Neck");
      this.neckRest = this.neck?.quaternion.clone();
      if (!this.targets.some(mesh => mesh.morphTargetDictionary?.viseme_aa !== undefined)) {
        throw new Error("Face asset has no speech shapes");
      }
      this.model.updateMatrixWorld(true);
      await this.preparePortrait(meshes, clippingPlanes);
      // The hair follows the skull, while neck skin deforms through the rig.
      // Do not transform the whole bust: the shoulders are the stationary reference.
      this.scene.updateMatrixWorld(true);
      if (!this.head || !this.neck) throw new Error("Face asset has no head/neck bones");
      this.head.attach(this.hairCard);
      this.setAppearance(this.appearance);
    }

    async preparePortrait(meshes, clippingPlanes) {
      const THREE = this.THREE;
      const texture = await new THREE.TextureLoader().loadAsync(new URL("assets/mesh-face/portrait-reference.png", baseURL).href);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
      this.portraitParts = [];
      this.portraitBlink = { value: 0 };
      this.portraitGaze = { value: new THREE.Vector2() };
      // Frontal registration: eyes near y=1.65, lip seam near y=1.58.
      // UVs are calculated once at rest, so the photograph moves with the rig.
      for (const mesh of meshes) {
        const name = mesh.name.toLowerCase();
        if (name.includes("casualsuit")) continue;
        const hidden = /ponytail|eyebrow|eyelash/.test(name);
        const project = name === "human" || name.includes("high-poly");
        const part = { mesh, material: mesh.material, uv: mesh.geometry.getAttribute("uv"), hidden };
        if (project) {
          const positions = mesh.geometry.getAttribute("position"), uv = new Float32Array(positions.count * 2);
          for (let i = 0; i < positions.count; i++) {
            const x = positions.getX(i), y = positions.getY(i);
            const mouth = Math.exp(-(((y - 1.58) / .025) ** 2)) * Math.exp(-((x / .055) ** 4));
            uv[i * 2] = .5 + x / .32 * (1 + .22 * mouth);
            uv[i * 2 + 1] = (y - 1.45) / .36 - .024 * mouth;
          }
          part.projectedUV = new THREE.BufferAttribute(uv, 2);
          part.portraitMaterial = new THREE.MeshBasicMaterial({ map: texture, clippingPlanes });
          part.portraitMaterial.onBeforeCompile = shader => {
            shader.uniforms.portraitBackground = { value: new THREE.Color(0x050907) };
            shader.uniforms.portraitBlink = this.portraitBlink;
            shader.uniforms.portraitGaze = this.portraitGaze;
            shader.vertexShader = "varying vec3 portraitRest;\n" + shader.vertexShader.replace(
              "#include <begin_vertex>", "#include <begin_vertex>\nportraitRest = position;");
            shader.fragmentShader = "varying vec3 portraitRest; uniform vec3 portraitBackground; uniform float portraitBlink; uniform vec2 portraitGaze;\n" + shader.fragmentShader.replace(
              "#include <map_fragment>", `#include <map_fragment>
                vec2 iris=vec2((abs(vMapUv.x-.5)-.111)/.03,(vMapUv.y-.557)/.024);
                float gazeMask=1.0-smoothstep(.65,1.3,length(iris));
                diffuseColor.rgb=texture2D(map,vMapUv+portraitGaze*gazeMask*(1.0-portraitBlink)).rgb;
                float interior=(1.0-smoothstep(.12,.135,portraitRest.z))
                  *(1.0-smoothstep(.018,.03,abs(portraitRest.x)))
                  *smoothstep(1.54,1.55,portraitRest.y)*(1.0-smoothstep(1.60,1.61,portraitRest.y));
                diffuseColor.rgb=mix(diffuseColor.rgb,vec3(.001,.003,.002),interior);
                vec2 eye=vec2((abs(portraitRest.x)-.035)/.024,(portraitRest.y-1.65)/.013);
                float lid=(1.0-smoothstep(.75,1.1,length(eye)))*portraitBlink;
                vec3 skin=texture2D(map,vec2(vMapUv.x,vMapUv.y+.13)).rgb;
                float lash=1.0-smoothstep(.001,.0025,abs(portraitRest.y-1.648-.003*eye.x*eye.x));
                skin=mix(skin,vec3(.001,.005,.002),lash);
                diffuseColor.rgb=mix(diffuseColor.rgb,skin,lid);
                float ink=smoothstep(.001,.009,max(diffuseColor.r,max(diffuseColor.g,diffuseColor.b)));
                diffuseColor.rgb=mix(portraitBackground,diffuseColor.rgb,ink);
              `);
          };
        } else if (/teeth|tongue/.test(name)) {
          part.portraitMaterial = new THREE.MeshBasicMaterial({ color: name.includes("teeth") ? 0x5d8468 : 0x122319, clippingPlanes });
        }
        this.portraitParts.push(part);
      }
      // A masked shell retains the portrait's hair silhouette. The opaque centre
      // is removed so open lips and eyes cannot reveal a second, static face.
      const material = new THREE.ShaderMaterial({
        uniforms: { portrait: { value: texture } }, transparent: true, depthWrite: false,
        vertexShader: `varying vec2 portraitUV;
          void main() { portraitUV=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
        fragmentShader: `uniform sampler2D portrait; varying vec2 portraitUV;
          void main() {
            vec4 color=texture2D(portrait,portraitUV);
            vec2 p=(portraitUV-vec2(.5,.49))/vec2(.235,.32);
            float hole=smoothstep(.88,1.03,length(p));
            float ink=smoothstep(.005,.035,max(color.r,max(color.g,color.b)));
            // The card supplies hair, not a second neck/shoulder silhouette.
            gl_FragColor=vec4(color.rgb,hole*ink*smoothstep(.23,.30,portraitUV.y));
            #include <tonemapping_fragment>
            #include <colorspace_fragment>
          }`,
      });
      this.portraitTexture = texture;
      const hairGeometry = new THREE.PlaneGeometry(.32, .36, 40, 48);
      const hairPositions = hairGeometry.attributes.position;
      // Match the frontal scalp depth. A flat layer behind the skull moves
      // opposite the face in yaw, even when both follow the same head bone.
      for (let i = 0; i < hairPositions.count; i++) {
        const x = hairPositions.getX(i), y = hairPositions.getY(i) + 1.63;
        const radius = (x / .165) ** 2 + ((y - 1.68) / .17) ** 2;
        hairPositions.setZ(i, .02 + .135 * Math.sqrt(Math.max(0, 1 - radius)));
      }
      hairGeometry.computeVertexNormals();
      this.hairCard = new THREE.Mesh(hairGeometry, material);
      this.hairCard.position.set(0, 1.63, 0);
      this.scene.add(this.hairCard);
    }

    setAppearance(value) {
      this.appearance = value === "rig" ? "rig" : "portrait";
      const portrait = this.appearance === "portrait";
      for (const part of this.portraitParts || []) {
        part.mesh.visible = !(portrait && part.hidden);
        part.mesh.material = portrait && part.portraitMaterial ? part.portraitMaterial : part.material;
        if (part.projectedUV) part.mesh.geometry.setAttribute("uv", portrait ? part.projectedUV : part.uv);
      }
      const wire = this.model?.getObjectByName("Human_wire");
      if (wire) wire.visible = !portrait;
      if (this.hairCard) this.hairCard.visible = portrait;
    }

    setShape(name, value) {
      for (const mesh of this.targets) {
        const index = mesh.morphTargetDictionary[name];
        if (index !== undefined) mesh.morphTargetInfluences[index] = Math.max(0, Math.min(1, value));
      }
    }

    draw(ctx, t, w, h, { state = "idle", mouthWeights = null, previewPose = null } = {}) {
      if (!this.ready) return false;
      this.resetMouth();
      const speaking = state === "speaking" && mouthWeights && previewPose == null;
      const statePreview = previewPose === 0 || previewPose === 16 || previewPose === 17;
      const motionState = previewPose === 0 ? "idle" : previewPose === 16 ? "listening" : previewPose === 17 ? "thinking" : state;
      const moving = !this.reducedMotion.matches && (previewPose == null || statePreview);
      const motion = this.motion.sample(t, motionState, moving);
      this.pose = previewPose ?? (speaking ? mouthWeights.indexOf(Math.max(...mouthWeights)) : STATE_POSE[state] ?? 0);
      if (speaking) {
        VISEMES.forEach((name, i) => { if (name) this.setShape("viseme_" + name, mouthWeights[i] * GAIN[i]); });
      } else if (this.pose > 0 && this.pose < 15) {
        this.setShape("viseme_" + VISEMES[this.pose], GAIN[this.pose]);
      }
      const shapes = {
        16: { browInnerUp: .12 }, 17: { browDownLeft: .18, eyeSquintRight: .12 },
        18: { browOuterUpLeft: .45, browInnerUp: .2 },
        19: { mouthSmileLeft: .55, mouthSmileRight: .55, cheekSquintLeft: .2, cheekSquintRight: .2 },
        20: { mouthSmileLeft: .6, mouthSmileRight: .6, jawOpen: .35 },
        21: { browInnerUp: .65, eyeWideLeft: .4, eyeWideRight: .4, jawOpen: .3 },
        22: { browInnerUp: .4, mouthFrownLeft: .18, mouthFrownRight: .18 },
        23: { mouthSmileLeft: .25, mouthSmileRight: .25, browInnerUp: .1 },
      };
      for (const [name, weight] of Object.entries(shapes[this.pose] || {})) this.setShape(name, weight);
      if (moving && ["idle", "listening", "thinking", "speaking"].includes(motionState)) {
        this.setShape("browInnerUp", motion.brow);
        this.setShape("browDownLeft", .18 * motion.thinking);
        this.setShape("eyeSquintRight", .12 * motion.thinking);
      }
      let blink = this.pose === 15 ? 1 : 0;
      if (moving) {
        if (this.blinkAt == null && t >= this.nextBlink) this.blinkAt = t;
        if (this.blinkAt != null) {
          const progress = (t - this.blinkAt) / 180;
          if (progress >= 1) { this.blinkAt = null; this.nextBlink = t + 4000 + Math.random() * 2000; }
          else blink = Math.sin(progress * Math.PI);
        }
      }
      this.setShape("eyeBlinkLeft", blink); this.setShape("eyeBlinkRight", blink);
      if (this.portraitBlink) this.portraitBlink.value = blink;
      if (this.portraitGaze) this.portraitGaze.value.set(motion.gazeX, motion.gazeY);
      if (this.neck) {
        this.neck.quaternion.copy(this.neckRest);
        this.neck.rotateX(motion.pitch * .25);
        this.neck.rotateY(motion.yaw * .2);
      }
      if (this.head) {
        this.head.quaternion.copy(this.headRest);
        this.head.rotateX(motion.pitch * .75);
        this.head.rotateY(motion.yaw * .8);
        this.head.rotateZ(motion.roll);
      }
      const height = Math.max(80, Math.min(700, h - 185));
      const width = Math.min(w, 900);
      if (width !== this.renderWidth || height !== this.renderHeight) {
        this.renderer.setSize(width, height, false);
        const halfHeight = Math.max(.205, .15 * height / width);
        this.camera.top = halfHeight; this.camera.bottom = -halfHeight;
        this.camera.left = -halfHeight * width / height; this.camera.right = -this.camera.left;
        this.camera.updateProjectionMatrix();
        this.renderWidth = width; this.renderHeight = height;
      }
      this.renderer.render(this.scene, this.camera);
      this.bounds = { x: (w - width) / 2, y: 20, width, height };
      ctx.drawImage(this.renderer.domElement, this.bounds.x, this.bounds.y, width, height);
      return true;
    }

    dispose() {
      const geometries = new Set(), materials = new Set(), textures = new Set(), skeletons = new Set();
      this.scene?.traverse(node => {
        if (node.geometry) geometries.add(node.geometry);
        if (node.skeleton) skeletons.add(node.skeleton);
        for (const material of [node.material].flat().filter(Boolean)) {
          materials.add(material);
          for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
        }
      });
      for (const part of this.portraitParts || []) {
        materials.add(part.material);
        if (part.portraitMaterial) materials.add(part.portraitMaterial);
        for (const value of Object.values(part.material)) if (value?.isTexture) textures.add(value);
      }
      if (this.portraitTexture) textures.add(this.portraitTexture);
      for (const resource of [...geometries, ...materials, ...textures, ...skeletons]) resource.dispose();
      this.renderer?.dispose();
      this.scene = null;
      this.renderer = null;
      this.targets = [];
      this.portraitParts = [];
      this.portraitTexture = this.hairCard = null;
      this.renderWidth = this.renderHeight = null;
    }
  }
  window.MeshAvatar = MeshAvatar;
})();
