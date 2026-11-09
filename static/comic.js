// Saved example comic. Images are requested only when its tab is opened.
globalThis.ClearFrameComic = (() => {
  const base = '/static/comics/hormuz-stick-figures-v1/';
  const pages = [
  {
    "title": "WHO IS CAUSING THE CRISIS?",
    "file": "page-01.png",
    "panels": [
      [
        {
          "speaker": "Caption",
          "text": "A reader follows one question through the report."
        },
        {
          "speaker": "READER balloon",
          "text": "What would end the Hormuz crisis?"
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "The NPR article acknowledges that the U.S. and Israel began the war."
        },
        {
          "speaker": "READER",
          "text": "So the story does not begin with shipping restrictions."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "NPR frames renewed U.S. strikes as protection and bargaining pressure."
        },
        {
          "speaker": "U.S. figure",
          "text": "Our pressure could bring Iran back to talks."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "Iran's state broadcaster reverses the explanation."
        },
        {
          "speaker": "Iranian commander",
          "text": "American military pressure and the blockade make shipping less secure."
        }
      ],
      [
        {
          "speaker": "Labels",
          "text": "U.S. policy frame: pressure could help\" and \"Press TV frame: pressure creates insecurity"
        },
        {
          "speaker": "READER",
          "text": "They disagree about what causes the problem and what counts as a response."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "A practical promise invites the next question."
        },
        {
          "speaker": "READER",
          "text": "If force might work, is that enough?"
        }
      ]
    ]
  },
  {
    "title": "THE ASSUMPTION UNDER THE TABLE",
    "file": "page-02.png",
    "panels": [
      [
        {
          "speaker": "Caption",
          "text": "Michael Singh is a former U.S. security official from the Bush administration."
        },
        {
          "speaker": "Singh",
          "text": "Words and force can both be used to seek negotiations."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "The article presents attacks as available instruments of policy."
        },
        {
          "speaker": "READER",
          "text": "Force is already on the menu."
        }
      ],
      [
        {
          "speaker": "READER",
          "text": "Before choosing a tool, shouldn't we ask whether using it is justified?"
        },
        {
          "speaker": "Caption",
          "text": "A question about effectiveness can leave a question about permission unexamined."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "The Omani comparison includes Iran's objection under the U.N. Charter."
        },
        {
          "speaker": "Oman perspective",
          "text": "We cannot assume attacks are justified merely because they might work."
        }
      ],
      [
        {
          "speaker": "READER",
          "text": "Reporting a legal objection does not prove it correct."
        },
        {
          "speaker": "Caption",
          "text": "It still makes permission to use force a separate issue."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "This is not an unconditional endorsement: NPR also acknowledges who began the war."
        },
        {
          "speaker": "READER",
          "text": "Who decides whether force may continue?"
        }
      ]
    ]
  },
  {
    "title": "SUCCESS IS NOT THE ONLY TEST",
    "file": "page-03.png",
    "panels": [
      [
        {
          "speaker": "Caption",
          "text": "The source article emphasizes Iranian responsiveness and lasting calm."
        },
        {
          "speaker": "U.S. executive",
          "text": "Would continued pressure produce talks and stable shipping?"
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "The comparison from an Israeli publication raises a different test."
        },
        {
          "speaker": "Congress figure",
          "text": "Where is the authorization for continued military action?"
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "The Jerusalem Post article describes a 60-day limit on unauthorized military action."
        },
        {
          "speaker": "READER",
          "text": "That question is separate from whether the attacks might help."
        }
      ],
      [
        {
          "speaker": "Executive balloon",
          "text": "Hostilities have ended."
        },
        {
          "speaker": "Caption",
          "text": "The comparison contrasts that claim with continuing attacks and a blockade."
        }
      ],
      [
        {
          "speaker": "READER",
          "text": "A useful result does not, by itself, answer the question of permission."
        },
        {
          "speaker": "Caption",
          "text": "The U.S. policy frame leaves officials more room to argue from expected benefits."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "Yet authorization is not the only question the comparison adds."
        },
        {
          "speaker": "READER",
          "text": "What if the terms of the bargain also need changing?"
        }
      ]
    ]
  },
  {
    "title": "WHO HAS TO CHANGE?",
    "file": "page-04.png",
    "panels": [
      [
        {
          "speaker": "Caption",
          "text": "Singh's explanation emphasizes Iranian divisions and the political risk of compromise."
        },
        {
          "speaker": "Singh",
          "text": "Iran's leaders may fear that compromise makes them look weak."
        }
      ],
      [
        {
          "speaker": "Trump balloon",
          "text": "A deal, or total surrender."
        },
        {
          "speaker": "Caption",
          "text": "The Omani comparison makes American demands another possible obstacle, without proving they caused the impasse."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "The Saudi comparison in Okaz puts changes on both sides of the table."
        },
        {
          "speaker": "Saudi Arabia",
          "text": "Reopening shipping requires reciprocal restraint, not Iranian concessions alone."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "Okaz also raises a possible shared fund involving the International Maritime Organization."
        },
        {
          "speaker": "Oman perspective",
          "text": "Could shared arrangements help keep shipping reliable?"
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "NPR does allow for Iranian transit management. Negotiation is not absent."
        },
        {
          "speaker": "READER",
          "text": "The gap is how far American policy changes and shared oversight are explored."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "These are possible arrangements, not an agreement the report says happened."
        },
        {
          "speaker": "READER",
          "text": "While leaders bargain, who bears the cost?"
        }
      ]
    ]
  },
  {
    "title": "WHOSE PAIN COUNTS?",
    "file": "page-05.png",
    "panels": [
      [
        {
          "speaker": "Caption",
          "text": "The source article gives attention to Americans facing higher food and gasoline prices."
        },
        {
          "speaker": "U.S. parent",
          "text": "Our everyday costs keep rising."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "The article links that hardship to Republican electoral risk."
        },
        {
          "speaker": "Republican lawmaker",
          "text": "Higher prices could leave us vulnerable in November."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "The comparison brings families' basic needs and farmers' unaffordable supplies into view."
        },
        {
          "speaker": "Family member",
          "text": "We need enough food."
        },
        {
          "speaker": "Farmer",
          "text": "I cannot afford basic supplies."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "A warning cited in the comparison widens attention to hunger and poverty."
        },
        {
          "speaker": "READER",
          "text": "Their hardship matters even when they cannot vote in U.S. elections."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "The analysis does not say American suffering is unreal."
        },
        {
          "speaker": "READER",
          "text": "It asks whether suffering elsewhere should independently constrain continued fighting."
        }
      ],
      [
        {
          "speaker": "Caption",
          "text": "Domestic political costs are only part of the picture."
        },
        {
          "speaker": "READER",
          "text": "An acceptable way out—for whom?"
        }
      ]
    ]
  },
  {
    "title": "A WIDER WAY OUT",
    "file": "page-06.png",
    "panels": [
      [
        {
          "speaker": "Caption",
          "text": "The reader returns to the original question with a wider set of tests."
        },
        {
          "speaker": "READER",
          "text": "What would end the Hormuz crisis?"
        }
      ],
      [
        {
          "speaker": "U.S. policy-frame figure",
          "text": "Would our pressure produce talks and lasting calm?"
        },
        {
          "speaker": "Iran state-media-frame figure",
          "text": "Is American pressure itself creating insecurity?"
        }
      ],
      [
        {
          "speaker": "Oman perspective",
          "text": "Permission to use force cannot be assumed."
        },
        {
          "speaker": "READER",
          "text": "The Israeli comparison also asks about congressional authority."
        }
      ],
      [
        {
          "speaker": "Saudi Arabia",
          "text": "Both sides may need to change."
        },
        {
          "speaker": "Oman perspective",
          "text": "American terms and shared arrangements also belong in the discussion."
        }
      ],
      [
        {
          "speaker": "READER",
          "text": "Whose costs count, and who gets to set the limits?"
        },
        {
          "speaker": "Caption",
          "text": "Shipping, power, permission, bargaining terms, and human hardship all enter the picture."
        }
      ],
      [
        {
          "speaker": "READER",
          "text": "I can see what each explanation brings forward—and what it leaves less examined."
        },
        {
          "speaker": "Caption",
          "text": "Coverage patterns do not establish journalists' intentions or a whole country's consensus."
        }
      ]
    ]
  }
];
  const escape = value => String(value).replace(/[&<>"']/g, character => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[character]));
  function render(){
    const navigation = pages.map((page,index) => '<a href="#comic-page-' + (index+1) + '" aria-label="Go to comic page ' + (index+1) + '">' + (index+1) + '</a>').join('');
    return '<div class="comic-report"><header class="comic-heading"><p class="eyebrow">Example comic · Strait of Hormuz</p>' +
      '<h3>Hormuz: a wider picture</h3><p>A six-page stick-figure story based on the saved ClearFrame comparison. Dialogue is reconstructed from the analysis.</p></header>' +
      '<nav class="comic-contents" aria-label="Comic pages">' + navigation + '</nav>' +
      pages.map((page,index) => {
        const number = index+1, src = base+page.file;
        const transcript = page.panels.map(panel => '<li>' + panel.map(line => '<p><strong>' + escape(line.speaker) + ':</strong> ' + escape(line.text) + '</p>').join('') + '</li>').join('');
        return '<section class="comic-page" id="comic-page-' + number + '" aria-labelledby="comic-heading-' + number + '">' +
          '<h4 id="comic-heading-' + number + '">Page ' + number + ' of ' + pages.length + ' · ' + escape(page.title) + '</h4>' +
          '<figure><a href="' + src + '" target="_blank" rel="noopener noreferrer" title="Open page ' + number + ' at full size">' +
          '<img data-comic-src="' + src + '" width="1199" height="1312" alt="Comic page ' + number + ': ' + escape(page.title) + '. A text transcript is available below."></a>' +
          '<figcaption><a href="' + src + '" target="_blank" rel="noopener noreferrer">Open full-size page</a></figcaption></figure>' +
          '<details class="comic-transcript"><summary>Read transcript</summary><ol>' + transcript + '</ol></details></section>';
      }).join('') + '</div>';
  }
  function load(panel){
    panel.querySelectorAll('img[data-comic-src]').forEach(image => {
      image.src = image.dataset.comicSrc;
      delete image.dataset.comicSrc;
    });
  }
  async function ready(panel){
    load(panel);
    await Promise.all([...panel.querySelectorAll('img')].map(image => image.decode().catch(() => {})));
  }
  return { render, load, ready };
})();

